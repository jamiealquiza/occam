#!/usr/bin/env python3

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

import redis, json, random, requests, logging, re, time, signal, sys, configparser, multiprocessing

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
pd_service_key = config['pagerduty']['service_key']

# General vars.
service_running = True
msgQueue = multiprocessing.Queue(multiprocessing.cpu_count() * 6)

# Checks.
checks = open('checks.py').read()
while "inRate" in checks: 
  checks = checks.replace('inRate(', 'checkRate("' + str(random.getrandbits(64)) + '", ', 1)

# Logging config.
log = logging.getLogger()
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s | %(levelname)s | %(message)s'))
log.addHandler(handler)
log.setLevel(logging.INFO)


##########
# INPUTS #
##########

def inMatch(message, key, ref):
    """Check if message with '@type' of 'type' has 'ref' key-value fields."""
    kv = ref.split(':')
    if "@type" in message and message['@type'] == key:
            if kv[0] in message and message[kv[0]] == kv[1]: return True
    return False

def inRegex(message, key, field, regex):
    """Apply 'regex' against 'field' for message with '@type' of 'key'."""
    rg = re.compile(regex)
    if "@type" in message and message['@type'] == key:
        if field in m:
          if re.match(rg, message[field]): return True
    return False

def checkRate(key, threshold, window):
    """Rate check."""
    expires = time.time() - window
    redis_conn.zremrangebyscore(key, '-inf', expires)
    now = time.time()
    redis_conn.zadd(key, now, now)
    if redis_conn.zcard(key) >= threshold:
        return True
    return False


###########
# OUTPUTS #
###########

def outConsole(message):
    """Writes to console."""
    log.info("Event Match: %s" % message)

def outPd(message, incident_key=None):
    """Writes to PagerDuty."""
    log.info("Event Match: %s" % message)

    url = "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
    alert = {
      "event_type": "trigger",
      "service_key": pd_service_key,
      "description": "occam_alert",
      "incident_key": "",
      "details": {}
    }

    # Append whole message as PD alert details.
    a['details'] = json.dumps(message)

    # Create incident_key if provided.
    if incident_key: alert['incident_key'] = alert['description'] = incident_key

    # Ship.
    resp = requests.post(url, data=json.dumps(alert))
    if resp.status_code != 200:
      log.warn("Error sending to PagerDuty: %s" % resp.content.decode('utf-8'))
    else:
      log.info("Message sent to PagerDuty: %s" % resp.content.decode('utf-8'))

def outHc(message, hc_meta):
    """Writes to HipChat."""
    log.info("Event Match: %s" % message)

    hc = config['hipchat'][hc_meta].split("_")
    url = "https://api.hipchat.com/v2/room/" + hc[0] + "/notification"

    notification = {
      "message": "<b>Occam Alert</b><br>" + json.dumps(message), 
      "message_format": "html"
    }
    # Ship.
    resp = requests.post(url,
      data=json.dumps(notification),
      params={'auth_token': hc[1]},
      headers={'content-type': 'application/json'})
    if resp.status_code != (200|204):
      log.warn("Error sending to HipChat: %s" % resp.content.decode('utf-8'))
    else:
      log.info("Message sent to HipChat")


#############
# INTERNALS #
#############

# Ensure Redis can be pinged.
def connRedis():
    while True:
        try:
            redis_conn.ping()
            log.info("Connected to Redis at %s:%d" % (redis_host, redis_port))
            break
        except Exception:
            log.warn("Redis unreachable, retrying in %ds" % redis_retry)
            time.sleep(redis_retry)

# Pops message batches from Redis and enqueues into 'msgQueue'.
def pollRedis():
    connRedis()
    while service_running:
        # Pipeline batches to reduce net latency.
        pipe = redis_conn.pipeline()
        pipe.lrange('messages', 0, 99)
        pipe.ltrim('messages', 100, -1)
        try:
            batch = pipe.execute()[0]
            if batch:
                msgQueue.put(batch)
            else:
                # Sleep if Redis list is empty to avoid
                # burning cycles. Save money. See world.
                time.sleep(3)
        except Exception:
            log.warn("Failed to poll Redis")
            connRedis(redis_conn)

# Pops batches from 'msgQueue' and iterates through checks.
def matcher():
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        batch = msgQueue.get()
        for m in batch:
          msg = json.loads(m.decode('utf-8'))
          exec(checks)


###########
# SERVICE #
###########

if __name__ == "__main__":
    # Start 1 matcher worker if single hw thread,
    # else greater of '2' and (hw threads - 2).
    n = lambda: 1 if multiprocessing.cpu_count() == 1 else max(multiprocessing.cpu_count()-1, 2)
    workers = [multiprocessing.Process(target=matcher) for x in range(n())]
    for i in workers:
        i.daemon = True
        i.start()

    # Sit-n-spin.
    try:
        pollRedis()
    except KeyboardInterrupt:
        log.info("Stopping workers")
        # Halt reading from Redis.
        service_running = False
        while True:
            if not msgQueue.empty():
                log.info("Waiting for in-flight messages")
                time.sleep(3)
            else:
                sys.exit(0)
