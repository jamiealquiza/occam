occam
=====

"The fewest assumptions" -A simple alerting service for JSON messages.

### Overview

Occam is a simple event matching service that allows you to write JSON message matching -> action logic using a simple, declarative Python syntax that is automatically parallelized under the hood.

The following in `checks.py` would look for a message with an '@type' field with the value 'type', then return whether or not 'somefield' exists and equals 'someval':
<pre>
if inMatch(msg, "type", "somefield:someval"): outConsole(msg)
</pre>
A matching message pushed into the reference Redis list:
<pre>
% redis-cli lpush messages '{ "@type": "type", "somefield": "someval" }'
</pre>
And Occam started, yielding the match:
<pre>
% ./occam.py
2014-12-23 19:05:15,549 | INFO | Connected to Redis at 127.0.0.1:6379
2014-12-23 19:05:36,576 | INFO | Event Match: { "@type": "type", "somefield": "someval" }
</pre>

Matching syntax can be nested to require additional conditions met to be considered a match or to trigger different actions depending on the number of conditions met:
<pre>
if inMatch(msg, "type", "somefield:someval"):
  if inMatch(msg, "type", "anotherfield:anotherval"
    outPd(msg)
  else:
    outConsole(msg)
</pre>
The above syntax would trigger a PagerDuty event (appending the 'msg' JSON document) if both 'somefield' and 'anotherfield' values were matched, but log to console if only 'somefield' was matched.

`checks.py` can contain any number of rules that every message will iterate against.

### Inputs / Outputs

#### inMatch
A basic equality check. With the input JSON 'msg' where the field '@type' = 'type', check if 'somefield' = 'somevalue'.
<pre>if inMatch(msg, "type", "somefield:somevalue")</pre>

#### inRegex
Python regex (re) matching. With the input JSON 'msg' where the field '@type' = 'type', checks pattern '.*' against the value of 'somefield'.
<pre>if inRegex(msg, "type", "somefield", ".*")</pre>

#### inRate
Rolling window rate check. Anchor function that is placed within a series of conditionals that requires a threshold of all preceding conditions to have been met '5' times within a '30' second rolling window, otherwise, the chain of conditions will be short-circuited.
<pre>
inRate(5, 30)
</pre>
In line example:
<pre>
if inMatch(msg, "type", "somefield:somevalue") and inRate(5, 30): outConsole(msg)
</pre>


#### outConsole
Writes 'msg' JSON to stdout upon match.
<pre>outConsole(msg)</pre>

#### outPd
Triggers a PagerDuty alert to the specified `service_key` (see `config` file) via the PagerDuty generic API, appending the whole 'msg' JSON output as the PagerDuty alert 'details' body. An [incident_key](https://developer.pagerduty.com/documentation/integration/events/trigger) and PagerDuty alert description is automatically generated unless specified as a second parameter:
<pre>outPd(msg, "web01-alerts")</pre>
It's also valid to use a portion of the message body to dynamically generate an incident key:
<pre>outPd(msg, msg['hostname'])</pre>
As well as a combination of a fixed string and unique message data:
<pre>outPd(msg, msg['somefield'] + " High Load")</pre>
Yielding:
<pre>
% ./occam.py
2015-01-10 09:44:25,592 | INFO | Connected to Redis at 127.0.0.1:6379
2015-01-10 09:44:31,611 | INFO | Event Match: {'somefield': 'somevalue', '@type': 'type'}
2015-01-10 09:44:31,622 | INFO | Starting new HTTPS connection (1): events.pagerduty.com
2015-01-10 09:44:32,617 | INFO | Message sent to PagerDuty: {"status":"success","message":"Event processed","incident_key":"somevalue High Load"}
</pre>

### Performance

 + Occam uses Redis as a local queue and is built on Python, inheritely not a very performant language. It's strongly recommended to ensure `hiredis` is installed.
 + All checks in `checks.py` are parallelized 'n' ways if 2 or more hardware threads are available, where 'n' = `max(multiprocessing.cpu_count()-1, 2)`. CPU load depends on complexity / size of checks applied.

### Misc.

Occam attempts to never ditch messages popped from Redis; the reader loop halts on shutdown and workers allow in-flight messages to complete:
<pre>
2015-01-09 10:36:42,353 | INFO | Connected to Redis at 127.0.0.1:6379
^C2015-01-09 10:36:49,211 | INFO | Stopping workers
2015-01-09 10:36:49,211 | INFO | Waiting for in-flight messages
</pre>
