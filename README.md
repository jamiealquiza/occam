occam
=====

"The fewest assumptions" - A simple matching / alerting service for JSON messages.

### Overview

Occam is a simple event matching service that allows you to apply field matching and alerting logic to a stream of JSON messages - using a simple, declarative Python syntax (stored in `checks.py`) that is automatically parallelized under the hood. Messages are read from a Redis list (using the list name 'messages'), populated by any means of choice. More robust queuing systems will be added in future updates.

Example use cases:
- [Collecting](https://github.com/jamiealquiza/ascender) package versions from every node in your infrastructure and triggering a HipChat message if specific versions of a given package are detected reported in
- Firing off a PagerDuty alert if a specific service has triggered a warning n times in x seconds across your whole fleet

The following in `checks.py` would check if any incoming messages included the field 'somefield' with the value 'someval', sending the output to console upon match:

```python
if inMatch(msg, "somefield", "someval"): outConsole(msg)
```

A message pushed into the reference Redis list:
<pre>
% redis-cli lpush messages '{ "somefield": "someval" }'
</pre>
Starting Occam, yielding the matched message according to the configured check:
<pre>
% ./occam.py
2015-01-21 11:20:21,920 | INFO | Waiting for Blacklist Rules sync
2015-01-21 11:20:21,922 | INFO | Connected to Redis at 127.0.0.1:6379
2015-01-21 11:20:21,922 | INFO | API - Listening at 0.0.0.0:8080
2015-01-21 11:20:27,127 | INFO | Redis Reader Task Started
2015-01-21 11:20:28,235 | INFO | Event Match: { "somefield": "someval" }
</pre>

Matching syntax can be nested and chained to require additional conditions:
```python
if inMatch(msg, "@type", "ssh-log") and inMatch(msg, "failed-attempt", "true"):
  outConsole(msg)
```
The above check would trigger a log to console, given a single message where the fields '@type' and 'failed-attempt' held the values 'ssh-log' and 'true', respectively.

Additional input / output actions exist that allow for more complex logic, such as sub-sampling or different output actions at each depth of conditions met. A real life configuration might look like:
```python
# A block of checks for all '@type' 'service-health' messages. 
if inMatch(msg, "@type": "service-health"):
  # If level is critical, alert via PagerDuty immediately.
  if inMatch(msg, "level", "critical"): outPd(msg)
  # If a single hosts reports 5 warning levels in 60s,
  if inMatch(msg, "level", "warning") and inRateKeyed("hostname", 5, 60):
    # And if within this warning treshold, 10 times in 30s it's due to the newly released 
    # 'new-service', then also send us a PagerDuty message:
    if inMatch(msg, "service", "new-service") and inRate(10, 30):
      outPd(msg)
  # Otherwise, just notify the ops HipChat room:
  else:
    outHc(msg, "ops-room")
```

Typically, you'd throw a top-level 'inMatch' for a whole class of message types (such as all messages where the field '@type' is 'apache') followed by all of the matching logic respecive to that message class. The above block would be all of the matching / alerting logic we care about solely in regards to 'service-health' messages.

### Inputs

#### inMatch
A basic equality check. With the input JSON 'msg', check if 'somefield' = 'somevalue'.
```python
if inMatch(msg, "somefield", "somevalue")
```

#### inRegex
Python regex (re) matching. With the input JSON 'msg', check pattern '.*' against the value of 'somefield'.
```python
if inRegex(msg, "somefield", ".*")
```

#### inRate
Rolling window rate check. Anchor function that is placed within a series of conditionals that requires a threshold of all preceding conditions to have been met '5' times within a '30' second rolling window, otherwise, the chain of conditions will be short-circuited.
```python
inRate(5, 30)
```
Example:
```python
if inMatch(msg, "somefield", "somevalue") and inRate(5, 30): outConsole(msg)
```

#### inRateKeyed
Rolling window rate check that dynamically generates seperate rate checks based on the value of a given message field.

```python
inRateKeyed("somefield", 5, 30)
```

Given the following checks logic, we would be able to use a generic rate checking syntax that would only trigger if the rate treshold were met from a single host:
```python
if inMatch(msg, "error-level", "warning") and inRateKeyed("hostname", 5, 30): outConsole(msg)
```

If this same check were configured using the basic 'inRate' check as follows:
```python
if inMatch(msg, "error-level", "warning") and inRate(5, 30): outConsole(msg)
```

The following message stream (within a 30s window) would trigger a match even though no single host exceeded the rate threshold:
<pre>
'{ "error-level": "warning", "hostname": "host-1" }'
'{ "error-level": "warning", "hostname": "host-1" }'
'{ "error-level": "warning", "hostname": "host-2" }'
'{ "error-level": "warning", "hostname": "host-2" }'
'{ "error-level": "warning", "hostname": "host-2" }'
</pre>

### Outputs

#### outConsole
Writes 'msg' JSON to stdout upon match.
```python
outConsole(msg)
```

#### outPd
Triggers a PagerDuty alert to the specified `service_key` alias (see `config` file - multiple service_keys by alias is supported) via the PagerDuty generic API, appending the whole 'msg' JSON output as the PagerDuty alert 'details' body. An [incident_key](https://developer.pagerduty.com/documentation/integration/events/trigger) and PagerDuty alert description is automatically generated unless specified as a second parameter:
```python
outPd(msg, "service-alias", "web01-alerts")
```

It's also valid to use a portion of the message body to dynamically generate an incident key:
```python
outPd(msg, "service-alias", msg['hostname'])
```
As well as a combination of a fixed string and unique message data:
```python
outPd(msg, "service-alias", msg['somefield'] + " High Load")
```

Yielding:
<pre>
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
```python
if inMatch(msg, "somefield", "somevalue"): outHc(msg, "test-room")
```

### Outage API
Note: work in progress.

#### Add Outage
<pre>
curl localhost:8080/ -XPOST -d '{"outage": "field:value:hours"}'
</pre>

#### Get Outages
<pre>
curl localhost:8080/
</pre>

#### Remove Outage
<pre>
localhost:8080/ -XDELETE -d '{"outage": "field:value"}'
</pre>

The Outage API allows you to maintain a global map of key-value 'blacklist' data that all messages are checked against and immediately dropped upon match. Blacklisting works as follows:
<pre>
% curl localhost:8080/ -XPOST -d '{"outage": "somefield:somevalue:2"}'
Request Received: {"outage": "somefield:somevalue:2"}
% curl localhost:8080/ -XPOST -d '{"outage": "somefield:anothervalue:6"}'
Request Received: {"outage": "somefield:anothervalue:6"}
</pre>

Occam propagating the rules to all workers running checks:
<pre>
% ./occam.py
2015-01-19 15:51:11,905 | INFO | API - Listening at 0.0.0.0:8080
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

### Performance

 + Occam uses Redis as a local queue and is built on Python, inheritely not a very performant language. It's strongly recommended to ensure `hiredis` is installed.
 + All checks in `checks.py` are parallelized 'n' ways if 2 or more hardware threads are available, where 'n' = `max(multiprocessing.cpu_count()-1, 2)`. CPU load depends on complexity / size of checks applied.
 + 'inRegex' is significantly more computationally expensive than basic 'inMatch' checks. It's recommended to pre-filter inbound messages to 'inRegex' as much as possible with basic matches.

### Misc.

Occam attempts to not ditch messages popped from Redis; the reader loop halts on shutdown and workers allow in-flight messages to complete:
<pre>
^C2015-01-09 10:36:49,211 | INFO | Stopping Reader Threads
2015-01-09 10:36:49,211 | INFO | Waiting for in-flight messages
</pre>

### Pending
Lots more inputs/outputs; see open issues.
