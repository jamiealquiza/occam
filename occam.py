#!/usr/bin/env python3
import redis, json, requests, logging, time, signal, sys, multiprocessing

# Config vars.
redis_retry = 10
redis_host = "127.0.0.1"
redis_port = 6379

# General vars.
service_running = True
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
        except Exception:
            log.warn("Redis unreachable, retrying in %ds" % redis_retry)
            time.sleep(redis_retry)

def pollRedis():
    r = redis.StrictRedis(host=redis_host, port=redis_port, db=0)
    connRedis(r)
    while service_running:
        pipe = r.pipeline()
        pipe.lrange('messages', 0, 99)
        pipe.ltrim('messages', 100, -1)
        try:
            batch = pipe.execute()[0]
            if batch:
                msgQueue.put(batch)
            else:
                time.sleep(3)
        except Exception:
            log.warn("Failed to poll Redis")
            connRedis(r)

def matcher():
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        batch = msgQueue.get()
        for msg in batch:
            exec(checks)

if __name__ == "__main__":
    n = lambda: 1 if multiprocessing.cpu_count() == 1 else max(multiprocessing.cpu_count()-1, 2)
    workers = [multiprocessing.Process(target=matcher) for x in range(n())]
    for i in workers:
        i.daemon = True
        i.start()

    try:
        pollRedis()
    except KeyboardInterrupt:
        log.info("Stopping workers")
        service_running = False
        while True:
            if not msgQueue.empty():
                log.info("Waiting for in-flight messages")
                time.sleep(3)
            else:
                sys.exit(0)
