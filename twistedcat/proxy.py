import binascii
from twisted.protocols import basic
from twisted.internet import protocol
from twisted.internet.interfaces import IStreamClientEndpoint, IStreamServerEndpoint

ALLOWED = """
PROTOCOLINFO
250-PROTOCOLINFO 1
250-VERSION Tor="0.2.6.10"
250 ControlPort
250 OK
250-AUTH METHODS=COOKIE,SAFECOOKIE COOKIEFILE="/var/run/tor/control.authcookie"
GETCONF ExitPolicy
GETINFO address
GETCONF ORPort
GETCONF DirPort
GETCONF BandwidthRate
GETINFO traffic/read
GETINFO traffic/written
GETCONF ControlPort
GETCONF BandwidthBurst
GETINFO fingerprint
GETCONF Nickname
.
""".strip().split("\n")

ALLOWED_PREFIXES = """
650 BW
AUTHENTICATE
GETINFO ns/id/
250+ns/id/
r 
s 
w 
p 
250-fingerprint=
250 Nickname=
250 ORPort=
250 DirPort=
250 BandwidthRate=
250-address=
250 BandwidthBurst=
250-traffic/read=
250-traffic/written=
250 ControlPort=
250 ExitPolicy=
""".strip().split("\n")

REPLACEMENTS = {
    "SETEVENTS NOTICE ERR NEWDESC NEWCONSENSUS WARN CIRC BW NS":
        "SETEVENTS NEWCONSENSUS BW"
}

FILTER = True

with open("/var/run/tor/control.authcookie", "rb") as f:
    AUTH_COOKIE = binascii.hexlify(f.read(32))

class LineProxyEndpointProtocol(basic.LineReceiver):
    noisy = True
    peer = None
    label = None

    def setPeer(self, peer):
        self.peer = peer

    def lineReceived(self, line):
        allow = False
        if FILTER == False:
            print "%s: %r" % (self.label, line)
            if line.startswith('AUTHENTICATE'):
                line = "AUTHENTICATE %s" % (AUTH_COOKIE,)
            self.peer.transport.write(line + self.delimiter)
            return
        if line.startswith('AUTHENTICATE'):
            line = "AUTHENTICATE %s" % (AUTH_COOKIE,)
            allow = True
        elif line in REPLACEMENTS:
            print "%s replacing %r with %r" % (self.label, line, REPLACEMENTS[line])
            line = REPLACEMENTS[line]
            allow = True
        elif line in ALLOWED:
            allow = True
        else:
            for prefix in ALLOWED_PREFIXES:
                if line.startswith(prefix):
                    allow = True
                    break
        if allow:
            print "%s allowed: %r" % (self.label, line,)
            self.peer.transport.write(line + self.delimiter)
        else:
            print "%s filtered: %r" % (self.label, line,)
            if self.label == "A":
                print "sending 510"
                self.sendLine("510 Command filtered")

    def connectionMade(self):
        if self.factory.peerFactory.protocolInstance is None:
            self.transport.pauseProducing()
        else:
            self.peer.setPeer(self)

            self.transport.registerProducer(self.peer.transport, True)
            self.peer.transport.registerProducer(self.transport, True)

            self.peer.transport.resumeProducing()

    def connectionLost(self, reason):
        self.transport.loseConnection()

        if self.factory.handleLostConnection is not None:
            self.factory.handleLostConnection()



class ProxyEndpointProtocolFactory(protocol.Factory):

    protocol = LineProxyEndpointProtocol

    def __init__(self, handleLostConnection=None, label=None):
        self.peerFactory = None
        self.protocolInstance = None
        self.handleLostConnection = handleLostConnection
        self.label = label

    def setPeerFactory(self, peerFactory):
        self.peerFactory = peerFactory

    def buildProtocol(self, *args, **kw):
        self.protocolInstance = protocol.Factory.buildProtocol(self, *args, **kw)
        self.protocolInstance.label = self.label

        if self.peerFactory.protocolInstance is not None:
            self.protocolInstance.setPeer(self.peerFactory.protocolInstance)

        return self.protocolInstance



class EndpointCrossOver(object):

    def __init__(self, endpoint1, endpoint2, handleError=None):
        self.endpoint1 = endpoint1
        self.endpoint2 = endpoint2
        self.handleError = handleError

    def _openEndpoint(self, endpoint, factory):
        if IStreamClientEndpoint.providedBy(endpoint):
            d = endpoint.connect(factory)
        elif IStreamServerEndpoint.providedBy(endpoint):
            d = endpoint.listen(factory)
        else:
            raise ValueError('must provide either IStreamClientEndpoint or IStreamServerEndpoint')

    def join(self):
        self.factory1 = ProxyEndpointProtocolFactory(handleLostConnection=self.handleError, label="A")
        self.factory2 = ProxyEndpointProtocolFactory(handleLostConnection=self.handleError, label="B")

        self.factory1.setPeerFactory(self.factory2)
        self.factory2.setPeerFactory(self.factory1)

        self._openEndpoint(self.endpoint1, self.factory1)
        self._openEndpoint(self.endpoint2, self.factory2)
