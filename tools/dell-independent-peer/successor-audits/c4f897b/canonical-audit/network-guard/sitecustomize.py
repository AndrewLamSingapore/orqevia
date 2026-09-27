# Verification harness safety restriction, not a kernel isolation guarantee.
import sys

def reject_network(event,args):
    if event == "socket.connect":
        sock,address=args
        if getattr(sock,"family",None) in (2,10):
            raise PermissionError("Independent audit: IP network disabled")
sys.addaudithook(reject_network)
