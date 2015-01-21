occam
=====

"The fewest assumptions" - A simple matching / alerting service for JSON messages.

### Overview

Occam is a simple event matching service that allows you to write JSON message matching -> action logic using a simple, declarative Python syntax that is automatically parallelized under the hood. Messages are read from a Redis list, populated by any means of choice.

The following in `checks.py` would look for a message with an '@type' field with the value 'type', then return whether or not 'somefield' exists and equals 'someval':
<pre>
if inMatch(msg, "type", "somefield:someval"): outConsole(msg)
</pre>
A message pushed into the reference Redis list:
<pre>
% redis-cli lpush messages '{ "@type": "type", "somefield": "someval" }'
</pre>
Then Occam started, yielding the match:
<pre>
% ./occam.py
2014-12-23 19:05:15,549 | INFO | Connected to Redis at 127.0.0.1:6379
2014-12-23 19:05:36,576 | INFO | Event Match: { "@type": "type", "somefield": "someval" }
</pre>

Matching syntax can be nested and chained to require additional conditions:
<pre>
if inMatch(msg, "type", "somefield:someval"):
  if inMatch(msg, "type", "anotherfield:anotherval"):
    outConsole(msg)
</pre>
The above syntax would console log the event (appending the 'msg' JSON document) if both 'somefield' and 'anotherfield' values were matched according to the checks syntax.

More complex logic can be formed, such as sub-sampling and different output actions at each level of conditions met:
<pre>
if inMatch(msg, "type", "somefield:someval") and inRate(5, 60):
  if inMatch(msg, "type", "anotherfield:anotherval") and inRate(10, 30):
      outPd(msg)
  else:
      outConsole(msg)
</pre>
The above syntax would write the message to console if >= 5 'somefield' = 'someval' matches were observed within a rolling 60 second window. If we were to exceed this threshold with say 35 matching events and >= 10 of those 35 events also held 'anotherfield' with the value 'anotherval' within a 30 second rolling window, we would trigger a PagerDuty alert (appending the message data - see 'Inputs/Outputs' section).

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

#### outHc
Sends a [room notification](https://www.hipchat.com/docs/apiv2/method/send_room_notification) to HipChat via the [v2 REST API](https://www.hipchat.com/docs/apiv2/auth) via a room ID and token. The room ID and token pair is referenced by an alias defined in the `config` file, with an underscore delimited \<id\>_\<token\> value:
<pre>
[hipchat]
test-room: 000000_00000000000000000000
</pre>
An alert output (in `checks.py`) configured to send a message to the corresponding HipChat room configuration:
<pre>
if inMatch(msg, "type", "somefield:somevalue"): outHc(msg, "test-room")
</pre>

### outEmail
Pending.

### outAscender
Pending.

### Performance

 + Occam uses Redis as a local queue and is built on Python, inheritely not a very performant language. It's strongly recommended to ensure `hiredis` is installed.
 + All checks in `checks.py` are parallelized 'n' ways if 2 or more hardware threads are available, where 'n' = `max(multiprocessing.cpu_count()-1, 2)`. CPU load depends on complexity / size of checks applied.

### Outage API
Note: work in progress.

The Outage API allows you to maintain a global map of key-value 'blacklist' data that all messages are checked against and immediately dropped upon match. Blacklisting works as follows:
<pre>
% curl localhost:8080/ -XPOST -d '{"outage": "somefield:somevalue:2"}'
Request Received: {"outage": "somefield:somevalue:2"}
% curl localhost:8080/ -XPOST -d '{"outage": "somefield:anothervalue:6"}'
Request Received: {"outage": "somefield:anothervalue:6"}
</pre>

Occam propagating the rules to all workers running checks:
<pre>
/occam.py
2015-01-19 15:51:21,905 | INFO | API - Listening at 0.0.0.0:8080
2015-01-19 15:51:21,906 | INFO | Connected to Redis at 127.0.0.1:6379
2015-01-19 15:51:28,609 | INFO | API - Outage Request: where 'somefield' == 'somevalue' for 2 hour(s)
2015-01-19 15:51:33,907 | INFO | Worker-0 - Blacklist Rules Updated: {"somefield": ["somevalue"]}
2015-01-19 15:51:33,909 | INFO | Worker-1 - Blacklist Rules Updated: {"somefield": ["somevalue"]}
2015-01-19 15:51:50,821 | INFO | API - Outage Request: where 'somefield' == 'anothervalue' for 6 hour(s)
2015-01-19 15:51:54,918 | INFO | Worker-1 - Blacklist Rules Updated: {"somefield": ["somevalue", "anothervalue"]}
2015-01-19 15:51:54,919 | INFO | Worker-0 - Blacklist Rules Updated: {"somefield": ["somevalue", "anothervalue"]}
</pre>

Every inbound message where 'somefield' equals 'somevalue' will be dropped for 2 hours, and for 6 hours where 'somefield' equals 'anothervalue'. Any number of fields and field-values can be specified, each combination with a separate outage duration.

Current outages can be fetched via:
<pre>
% curl localhost:8080/
{
  "Current Outages Scheduled": {
    "somefield": [
    "anothervalue",
    "somevalue"
    ]
    },
    "Occam Start Time": "2015-01-19 09:45:47"
  }
</pre>

Outage data is persisted in a Redis set, populated with a unique hash ID for each field-value pair. Each hash ID references a TTL'd Redis key with the field-value data- which is polled every 5 seconds, translated into a blacklist map, then propagated to the worker processes (which log any updates to the blacklist map).

Blacklist data can thus survive Occam service restarts as well as automatically propagate across a fleet of multiple Occam nodes processing a single stream of messages. The Outage API's hashing and storage method allows blacklist data to be written or updated from any node without collision, essentially allowing masterless read/write access to shared data.

### Misc.

Occam attempts to never ditch messages popped from Redis; the reader loop halts on shutdown and workers allow in-flight messages to complete:
<pre>
2015-01-09 10:36:42,353 | INFO | Connected to Redis at 127.0.0.1:6379
^C2015-01-09 10:36:49,211 | INFO | Stopping workers
2015-01-09 10:36:49,211 | INFO | Waiting for in-flight messages
</pre>

### Pending
Lots more inputs/outputs; see open issues.
