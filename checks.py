from matchers import inMatch, inRegex, inRate, inRateKeyed
from outputs import outConsole, outHc, outPd

def run(msg):
	##############################################
	# Checks logic. Do not edit above this line. #
	##############################################
    if inMatch(msg, "somefield", "somevalue"): outConsole(msg)
