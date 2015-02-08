from occam import redis_conn
import re
import inspect
import hashlib
import time

def inMatch(message, key, value):
    if key in message and message[key] == value: return True
    return False

def inRegex(message, key, regex):
    rg = re.compile(regex)
    if key in message:
        if re.search(rg, message[key]): return True
    return False


def inRate(threshold, window, key=None, uid=None):
    """Rate check."""
    # magic auto generate uid for most cases
    # if 2 inRate()s are on the same line, they will get the same key :(
    if uid is None:
        uid = _gen_ratecheck_uid()

    if key is not None:
        uid = uid + '-' + key

    expires = time.time() - window
    redis_conn.zremrangebyscore(uid, '-inf', expires)
    now = time.time()
    redis_conn.zadd(uid, now, now)
    if redis_conn.zcard(uid) >= threshold:
        return True
    return False

def inRateKeyed(message, key, threshold, window):
    uid = _gen_ratecheck_uid()
    return inRate(threshold, window, uid=uid, key=str(message.get(key, "dummy")))


### helpers

def _gen_ratecheck_uid():
    # get caller 2 levels up (should be in checks.py somewhere)
    (frame, filename, line_number,
             function_name, lines, index) = inspect.getouterframes(inspect.currentframe())[2]

    m = hashlib.md5()
    m.update(filename.encode('utf-8'))
    m.update(str(line_number).encode('utf-8'))
    uid = "rate-" + m.hexdigest()
    return uid
