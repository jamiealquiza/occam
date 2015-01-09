#!/usr/bin/env python3
import redis, json, requests, logging, time, signal, sys, configparser, multiprocessing

###########
# CONFIGS #
###########

# Config vars.
config = configparser.ConfigParser()
config.read('config')
redis_retry = int(config['redis']['retry'])
redis_host = config['redis']['host']
redis_port = int(config['redis']['port'])
pd_service_key = config['pagerduty']['service_key']
pd_description = config['pagerduty']['description']

# General vars.
service_running = True
checks = open('checks.py').read()
msgQueue = multiprocessing.Queue(multiprocessing.cpu_count() * 6)

# Logging config.
log = logging.getLogger()
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s | %(levelname)s | %(message)s'))
log.addHandler(handler)
log.setLevel(logging.INFO)

# PagerDuty generic API.
url = "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
alert = {
    "event_type": "trigger",
    "service_key": pd_service_key,
    "description": pd_description,
    "details": {}
}

##################
# INPUTS/OUTPUTS #
##################

# Check if message with '@type' of 'type' has 'ref' key-value fields.
def inMatch(message, key, ref):
    m = json.loads(message.decode('utf-8'))
    kv = ref.split(':')
    if "@type" in m and m['@type'] == key:
            if kv[0] in m and m[kv[0]] == kv[1]: return True
    return False

# Apply 'regex' against 'field' for message with '@type' of 'key'. 
def inRegex(message, key, field, regex):
  m = json.loads(message.decode('utf-8'))
  r = re.compile(regex)
  if "@type" in m and m['@type'] == key:
      if field in m:
        if re.match(r, m[field]): return True
  return False

# Send out to PagerDuty.
def outPd(message):
    log.info("Event Match: " + message.decode('utf-8'))
    a = alert
    # Append whole message as PD alert details.
    a['details'] = json.loads(message.decode('utf-8'))
    resp = requests.post(url, data=json.dumps(a))
    if resp.status_code != 200:
      log.warn("Error sending to PagerDuty: %s" % resp.content.decode('utf-8'))
    else:
      log.info("Message sent to PagerDuty: %s" % resp.content.decode('utf-8'))

# Write to console.
def outConsole(message):
   log.info("Event Match: " + message.decode('utf-8'))

#############
# INTERNALS #
#############

# Ensure Redis can be pinged.
def connRedis(r):
    while True:
        try:
            r.ping()
            log.info("Connected to Redis at %s:%d" % (redis_host, redis_port))
            break
        except Exception:
            log.warn("Redis unreachable, retrying in %ds" % redis_retry)
            time.sleep(redis_retry)

# Pops message batches from Redis and enqueues into 'msgQueue'.
def pollRedis():
    r = redis.StrictRedis(host=redis_host, port=redis_port, db=0)
    connRedis(r)
    while service_running:
        # Pipeline batches to reduce net latency.
        pipe = r.pipeline()
        pipe.lrange('messages', 0, 99)
        pipe.ltrim('messages', 100, -1)
        try:
            batch = pipe.execute()[0]
            if batch:
                msgQueue.put(batch)
            else:
                # Sleep if Redis list is empty to avoid
                # burning cycles.
                time.sleep(3)
        except Exception:
            log.warn("Failed to poll Redis")
            connRedis(r)

# Pops batches from 'msgQueue' and iterates through checks.
def matcher():
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        batch = msgQueue.get()
        for msg in batch:
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
