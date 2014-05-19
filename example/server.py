#!/usr/bin/env python
# -*- coding: utf-8 -*-
# server.py • an example server

import sys
import time
import BaseHTTPServer

HOST_NAME = ''
PORT_NUMBER = 8000
LOG_FILE = '/logs/access.log'

def log(format, *args):
    sys.stderr.write('%s: %s\n' % (time.asctime(), format % args))
    sys.stderr.flush()

class MyHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log(format, *args)

    def do_GET(s):
        """Respond to a GET request."""
        s.send_response(200)
        s.send_header("Content-type", "text/plain")
        s.end_headers()
        s.wfile.write("The server is up!\n")
        s.wfile.write("You accessed path: %s\n" % s.path)

if __name__ == '__main__':
    sys.stderr = open(LOG_FILE, 'a')
    server_class = BaseHTTPServer.HTTPServer
    httpd = server_class((HOST_NAME, PORT_NUMBER), MyHandler)
    log('Server starts - %s:%s', HOST_NAME, PORT_NUMBER)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    log('Server stops - %s:%s', HOST_NAME, PORT_NUMBER)
    sys.stderr.close()
