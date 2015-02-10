# Simple examples
from matchers import inMatch, inRegex, inRate, inRateKeyed
from outputs import outConsole, outHc, outPd

def run(msg):
    if inMatch(msg, "somefield", "somevalue"): outConsole(msg)
