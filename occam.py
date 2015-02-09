#!/usr/bin/env python3

# This might have a severe lack of Pythonism or OOP. http://knowyourmeme.com/memes/deal-with-it.

# The MIT License (MIT)
#
# Copyright (c) 2015 Jamie Alquiza
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# The MIT License (MIT)
#
# Copyright (c) 2014 Jamie Alquiza
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import redis, json, random, requests, logging, re, time, signal, hashlib, sys, configparser, multiprocessing, traceback
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

import checks

###########
# CONFIGS #
###########

# Config vars.
config = configparser.ConfigParser()
config.read('config')
redis_retry = int(config['redis']['retry'])
redis_host = config['redis']['host']
redis_port = int(config['redis']['port'])
redis_conn = redis.StrictRedis(host=redis_host, port=redis_port, db=0)

# General vars.
bl_first_sync = False
msgQueue = multiprocessing.Queue(multiprocessing.cpu_count() * 6)
statsQueue = multiprocessing.Queue()
start_time = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')

# Logging config.
log = logging.getLogger()
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s | %(levelname)s | %(message)s'))
log.addHandler(handler)
log.setLevel(logging.INFO)

#######################
# WORKERS / PROCESSES #
#######################

class Matcher(multiprocessing.Process):
    """Worker that pops batches from 'msgQueue' and iterates through checks.py"""
    def __init__(self, worker_id, queue):
        multiprocessing.Process.__init__(self)
        self.daemon = True
        self.worker_id = worker_id
        self.queue = queue

    def run(self):
        log.info("Match worker %d started" % self.worker_id)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        bl_rules = {}
        while True:
            # Look for blacklist rules.
            if not self.queue.empty():
                bl_rules =  self.queue.get(False)
                log.info("Worker-%s - Blacklist Rules Updated: %s" %
                  (self.worker_id, json.dumps(bl_rules)))
            # Handle message batches.
            try:
                batch = msgQueue.get(True, 3)
                for m in batch:
                    try:
                        msg = json.loads(m.decode('utf-8'))
                        for k in bl_rules:
                            if k in msg:
                                if msg[k] in bl_rules[k]: break
                        else:
                            try:
                                checks.run(msg)
                            except:
                                log.error("Exception occurred processing message:\n%s" % 
                                  (traceback.format_exc()))
                    except:
                        continue
            except:
                continue

###################
# TASKS / THREADS #
###################

class RedisReader(Thread):
    """Outputs periodic stats info"""
    def __init__(self):
        Thread.__init__(self)
        self.running = True

    # Pops message batches from Redis and enqueues into 'msgQueue'.
    def run(self):
        log.info("Redis Reader Task Started")
        while self.running:
            # Pipeline batches to reduce net latency.
            pipe = redis_conn.pipeline()
            pipe.lrange('messages', 0, 99)
            pipe.ltrim('messages', 100, -1)
            try:
                batch = pipe.execute()[0]
                if batch:
                    msgQueue.put(batch)
                    statsQueue.put(len(batch))
                else:
                    # Sleep if Redis list is empty to avoid
                    # burning cycles. Save money. See world.
                    time.sleep(3)
            except Exception:
                log.warn("Failed to poll Redis")
                self.try_redis_connection(redis_conn)

    def stop(self):
            self.running = False
            log.info("Redis Reader Task Stopping")

    # Ensure Redis can be pinged.
    def try_redis_connection(self):
        while True:
            try:
                redis_conn.ping()
                log.info("Connected to Redis at %s:%d" % (redis_host, redis_port))
                break
            except Exception:
                log.warn("Redis unreachable, retrying in %ds" % redis_retry)
                time.sleep(redis_retry)

class Blacklister(Thread):
    """Syncs blacklist rules with Redis"""
    def __init__(self, queues):
        Thread.__init__(self)
        self.daemon = True
        self.queues = queues

    def run(self):
        global bl_first_sync
        blacklist = {}
        while True:
            blacklist_update = self.fetch_blacklist()
            if blacklist != blacklist_update:
                blacklist = blacklist_update
                for i in self.queues: i.put(blacklist)
            bl_first_sync = True
            time.sleep(5)

    def fetch_blacklist(self):
        blacklist_update = {}
        # What rule keys exist?
        blacklist_keys = redis_conn.smembers('blacklist')
        for i in blacklist_keys:
            k = i.decode('utf-8')
            get = redis_conn.get(k)
            if get == None:
                # Rule key was likely expired, remove from blacklist set.
                redis_conn.srem('blacklist', k)
            else:
                kv = get.decode('utf-8').split(':')
                # Create blacklist key for rule field if it doesn't exist,
                # or append to existing.
                if not kv[0] in blacklist_update:
                    blacklist_update[kv[0]] = []
                    blacklist_update[kv[0]].append(kv[1])
                else:
                    blacklist_update[kv[0]].append(kv[1])
        return blacklist_update


class Statser(Thread):
    """Outputs periodic stats info"""
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True

    def run(self):
        count_current = count_previous = 0
        while True:
            stop = time.time()+5
            while time.time() < stop:
                if not statsQueue.empty():
                    count_current += statsQueue.get()
                else:
                    time.sleep(0.25)
            if count_current > count_previous:
                # We divide by the actual duration because
                # thread scheduling / run time can't be trusted.
                duration = time.time() - stop + 5
                log.info("Last %.1fs: polled %.2f messages/sec." % (duration, count_current / duration))
            count_previous = count_current = 0

# REST API 
# Init. This for real needs to be significantly better.
class Api(Thread):
    """Outputs periodic stats info"""
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True

    def run(self):
        server = HTTPServer((config['api']['listen'], int(config['api']['port'])), ApiCalls)
        log.info("API - Listening at %s:%s" % (config['api']['listen'], config['api']['port']))
        server.serve_forever()

class ApiCalls(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            # Response message.
            status = {
              "Occam Start Time": start_time 
            }
            # Build outage meta.
            blacklist = getattr(Blacklister, fetch_blacklist)()
            if not bool(blacklist): blacklist = "None"
            status['Current Outages Scheduled'] = blacklist
            self.wfile.write(bytes("\n" + json.dumps(status, indent=2, sort_keys=True) + "\n", "utf-8"))
        else:
            self.wfile.write(bytes("Request Invalid\n", "utf-8"))

    def do_POST(self):
        if self.path == '/':
            # Do stuff.
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            # Handle request.
            try:
                outage_meta = json.loads(post_data)['outage'].split(':')
                log.info("API - Outage Request: where '%s' == '%s' for %s hour(s)" %
                  (outage_meta[0], outage_meta[1], outage_meta[2]))
                # Generate outage key data.
                outage_id = hashlib.sha1(str(outage_meta[:2]).encode()).hexdigest()
                outage_expires = int(outage_meta[2]) * 3600
                outage_kv = str(outage_meta[0] + ':' + outage_meta[1])
                # Set outage.
                redis_conn.setex(outage_id, outage_expires, outage_kv)
                redis_conn.sadd('blacklist', outage_id)
                # Send response.
                self.wfile.write(bytes("Request Received - POST: " + post_data + "\n", "utf-8"))
            except:
                self.wfile.write(bytes("Request Error: " + post_data + "\n", "utf-8"))

    def do_DELETE(self):
        if self.path == '/':
            # Do stuff.
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            # Handle request.
            try:
                outage_meta = json.loads(post_data)['outage'].split(':')
                log.info("API - Delete Outage Request: where '%s' == '%s'" %
                  (outage_meta[0], outage_meta[1]))
                # Generate outage key data.
                outage_id = hashlib.sha1(str(outage_meta[:2]).encode()).hexdigest()
                # Set outage.
                redis_conn.delete(outage_id)
                # Send response.
                self.wfile.write(bytes("Request Received - DELETE: " + post_data + "\n", "utf-8"))
            except:
                self.wfile.write(bytes("Request Error: " + post_data + "\n", "utf-8"))

###########
# SERVICE #
###########

if __name__ == "__main__":
    # Start 1 matcher worker if single hw thread, else greater of '2' and (hw threads - 2).
    n = 1 if multiprocessing.cpu_count() == 1 else max(multiprocessing.cpu_count()-1, 2)

    # Initialize workers and queues.
    # Append queues to list that's fed to the blacklister thread.
    blacklist_queues = []
    for i in range(n):
        queue_i = multiprocessing.Queue()
        blacklist_queues.append(queue_i)
        worker = Matcher(i, queue_i)
        worker.start()
        
    # Start 'blacklister()' sync thread.
    blacklister = Blacklister(blacklist_queues)
    blacklister.start()

    # Start REST 'api()' and 'statser()' threads.
    statser = Statser()
    statser.start()
    api = Api()
    api.start()

    # Redis thread.
    redis_reader = RedisReader()

    # Sit-n-spin.
    try:
        log.info("Waiting for Blacklist Rules sync")
        # Avoiding adding communication to worker processes
        # to ensure initial blacklist sync occurred, instead
        # we wait for the first 'blacklister()' thread sync event
        # and sleep for 5 seconds. 
        while not bl_first_sync:
            time.sleep(0.2)
        time.sleep(5)
        # Then start main Redis reader task.
        redis_reader.start()
    except KeyboardInterrupt:
        redis_reader.stop()
        while True:
            if not msgQueue.empty():
                log.info("Waiting for in-flight messages")
                time.sleep(3)
            else:
                # Do something smarter than time.sleep(n) eventually.
                time.sleep(1)
                sys.exit(0)
