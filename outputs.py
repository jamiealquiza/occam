import json
import multiprocessing
import requests

from log import log


alertsQueue = multiprocessing.Queue()


def outConsole(message):
    """Writes message to console"""
    alertsQueue.put(("outConsole", message)) 

def outPd(message, service_alias, incident_key=None):
    """Writes message to PagerDuty"""
    alertsQueue.put(("outPd", message, service_alias, incident_key))
    
def outHc(message, hc_meta):
    """Writes message to HipChat"""
    alertsQueue.put(("outHc", message, hc_meta))


################
# OUTPUT LOGIC #
################

def outConsoleHandler(meta):
    message = meta[1]
    log.info("Event Match: %s" % message)

def outHcHandler(meta, config):
    message, hc_meta = meta[1:]
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


def outPdHandler(meta, config):
    message, service_alias, incident_key = meta[1:]
    log.info("Event Match: %s" % message)

    service_key = config['pagerduty'][service_alias]
    url = "https://events.pagerduty.com/generic/2010-04-15/create_event.json"
    alert = {
      "event_type": "trigger",
      "service_key": service_key,
      "description": "occam_alert",
      "incident_key": "",
      "details": {}
    }

    # Append whole message as PD alert details.
    alert['details'] = json.dumps(message)

    # Create incident_key if provided.
    if incident_key: alert['incident_key'] = alert['description'] = incident_key

    # Ship.
    resp = requests.post(url, data=json.dumps(alert))
    if resp.status_code != 200:
        log.warn("Error sending to PagerDuty: %s" % resp.content.decode('utf-8'))
    else:
        log.info("Message sent to PagerDuty: %s" % resp.content.decode('utf-8'))
