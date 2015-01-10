#!/usr/bin/env python3
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

# PagerDuty generic API.
url = "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
alert = {
    "event_type": "trigger",
    "service_key": pd_service_key,
    "description": "",
    "incident_key": "",
    "details": {}
}

##################
# INPUTS/OUTPUTS #
##################

# Check if message with '@type' of 'type' has 'ref' key-value fields.
def inMatch(message, key, ref):
    kv = ref.split(':')
    if "@type" in message and message['@type'] == key:
            if kv[0] in message and message[kv[0]] == kv[1]: return True
    return False

# Apply 'regex' against 'field' for message with '@type' of 'key'.
def inRegex(message, key, field, regex):
  rg = re.compile(regex)
  if "@type" in message and message['@type'] == key:
      if field in m:
        if re.match(rg, message[field]): return True
  return False

# Rate check.
def checkRate(key, threshold, window):
    expires = time.time() - window
    redis_conn.zremrangebyscore(key, '-inf', expires)
    now = time.time()
    redis_conn.zadd(key, now, now)
    if redis_conn.zcard(key) >= threshold:
        return True
    return False

# Sent out to PagerDuty.
def outPd(message, incident_key=None):
    log.info("Event Match: %s" % message)
    a = alert
    # Append whole message as PD alert details.
    a['details'] = json.dumps(message)
    # Create incident_key if provided.
    if incident_key:
      a['incident_key'] = a['description'] = incident_key
    else:
      a['description'] = "occam_alert"
    # Ship.
    resp = requests.post(url, data=json.dumps(a))
    if resp.status_code != 200:
      log.warn("Error sending to PagerDuty: %s" % resp.content.decode('utf-8'))
    else:
      log.info("Message sent to PagerDuty: %s" % resp.content.decode('utf-8'))

# Write to console.
def outConsole(message):
   log.info("Event Match: %s" % message)

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
