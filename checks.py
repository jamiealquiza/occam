# Simple examples
from matchers import inMatch, inRegex, inRate, inRateKeyed
from outputs import outConsole, outHc, outPd


def run(msg):
    if inRate(5, 30): outConsole(msg)

    # keyed rate
    if inRateKeyed(msg, "somekeyfield", 5, 30): outConsole(msg)

    if inMatch(msg, "somefield", "somevalue"): outConsole(msg)
    if inRegex(msg, "somefield", ".*"): outConsole(msg)
