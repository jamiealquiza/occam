#!/usr/bin/env python3
import redis, json, requests, logging, time, multiprocessing
from threading import Thread

# General vars.
redis_retry = 10
redis_host = "127.0.0.1"
redis_port = 6379
checks = open('checks.py').read()
msgQueue = multiprocessing.Queue()

# Logging config.
log = logging.getLogger()
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s | %(levelname)s | %(message)s'))
log.addHandler(handler)
log.setLevel(logging.INFO)



url = "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
alert = {
    "service_key": "",
    "event_type": "trigger",
    "description": "occam",
    "details": {}
}

def inMatch(message, key, ref):
    m = json.loads(message.decode('utf-8'))
    kv = ref.split(':')
    if "@type" in m and m['@type'] == key:
            if kv[0] in m and m[kv[0]] == kv[1]:
                return True
    return False

def outPd(message):
    a = alert
    a['details'] = json.loads(message.decode('utf-8'))
    resp = requests.post(url, data=json.dumps(a))
    log.info("PagerDuty: " + json.dumps(a))

def outConsole(message):
   log.info("Event Match: " + message.decode('utf-8'))

def connRedis(r):
    while True:
        try:
            r.ping()
            log.info("Connected to Redis at %s:%d" % (redis_host, redis_port))
            break
        except:
            log.warn("Redis unreachable. Retrying in %ds." % redis_retry)
            time.sleep(redis_retry)

def pollRedis():
    r = redis.StrictRedis(host=redis_host, port=redis_port, db=0)
    connRedis(r)
    # Add try.
    while True:
        pipe = r.pipeline()
        pipe.lrange('messages', 0, 99)
        pipe.ltrim('messages', 100, -1)
        batch = pipe.execute()[0]
        if batch:
            msgQueue.put(batch)
        else:
            time.sleep(3)

def matcher():
    while True:
        batch = msgQueue.get()
        for msg in batch:
            exec(checks)

# use queue
if __name__ == "__main__":
    nWorkers = lambda: 1 if multiprocessing.cpu_count() == 1 else max(multiprocessing.cpu_count()-1, 2)
    workers = [multiprocessing.Process(target=matcher) for x in range(nWorkers())]
    for i in workers:
        i.start()
    reader = [Thread(target=pollRedis) for x in range(2)]
    for i in reader:
        i.start()
    for i in reader: i.join()
