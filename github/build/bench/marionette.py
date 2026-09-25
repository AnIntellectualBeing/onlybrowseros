import json, socket, time

class Marionette:
    def __init__(self, port=2828, timeout=60):
        deadline = time.time() + timeout
        while True:
            try:
                self.s = socket.create_connection(("127.0.0.1", port), timeout=30)
                break
            except OSError:
                if time.time() > deadline: raise
                time.sleep(1)
        self.buf = b""; self.id = 0
        self.recv()
        self.cmd("WebDriver:NewSession", {"capabilities": {}})
        self.cmd("Marionette:SetContext", {"value": "chrome"})

    def recv(self):
        while b":" not in self.buf: self.buf += self.s.recv(65536)
        n, _, rest = self.buf.partition(b":"); n = int(n)
        while len(rest) < n: rest += self.s.recv(65536)
        self.buf = rest[n:]
        return json.loads(rest[:n])

    def cmd(self, name, params=None):
        self.id += 1
        data = json.dumps([0, self.id, name, params or {}]).encode()
        self.s.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self.recv()
            if msg[0] == 1 and msg[1] == self.id:
                if msg[2]: raise RuntimeError(msg[2])
                return msg[3]

    def js(self, script):
        return self.cmd("WebDriver:ExecuteAsyncScript", {"script": script, "args": [], "scriptTimeout": 60000})["value"]

PROCS = """
const done = arguments[arguments.length - 1];
ChromeUtils.requestProcInfo().then(info => done(info.children.map(c => ({
  pid: c.pid, type: c.type, origin: c.origin || "",
  urls: (c.windows || []).map(w => w.documentURI ? w.documentURI.spec : "?")}))));
"""
MINIMIZE = """
const done = arguments[arguments.length - 1];
Cc["@mozilla.org/memory-reporter-manager;1"].getService(Ci.nsIMemoryReporterManager)
  .minimizeMemoryUsage(() => done(true));
"""
