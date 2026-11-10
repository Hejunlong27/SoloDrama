"""用 Chrome DevTools 协议驱动一次真实点击，验收「历史版本」弹窗。

为什么不用 headless --screenshot：那个只能截首屏，点不开弹窗。
本机没有 Playwright，所以直接用 CDP 的 Runtime.evaluate 注入点击，再截全页。

用法：
    python docs/design/shots/_snap_versions.py <ws> <out.png>
"""
import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


def cdp_targets():
    with urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=10) as r:
        return json.load(r)


def ws_url():
    for t in cdp_targets():
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    raise SystemExit("没有找到 page target")


def main():
    ws_path, out = sys.argv[1], sys.argv[2]
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--remote-debugging-port=%d" % PORT,
        "--window-size=1680,1050",
        "--user-data-dir=%s" % (pathlib.Path(out).parent / "_cdp_profile"),
        "about:blank",
    ])
    try:
        for _ in range(40):
            try:
                url = ws_url()
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise SystemExit("Chrome 没起来")

        # 极简 WebSocket 客户端（避免额外依赖）
        import socket
        import struct
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        s = socket.create_connection((host, int(port)), timeout=20)
        key = base64.b64encode(b"1234567890abcdef").decode()
        s.sendall((
            "GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)
        ).encode())
        s.recv(4096)

        def send(obj):
            data = json.dumps(obj).encode()
            hdr = bytearray([0x81])
            ln = len(data)
            if ln < 126:
                hdr.append(0x80 | ln)
            elif ln < 65536:
                hdr.append(0x80 | 126)
                hdr += struct.pack(">H", ln)
            else:
                hdr.append(0x80 | 127)
                hdr += struct.pack(">Q", ln)
            mask = b"\x01\x02\x03\x04"
            hdr += mask
            s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

        def recv():
            buf = b""
            while len(buf) < 2:
                buf += s.recv(65536)
            ln = buf[1] & 0x7F
            off = 2
            if ln == 126:
                while len(buf) < 4:
                    buf += s.recv(65536)
                ln = struct.unpack(">H", buf[2:4])[0]
                off = 4
            elif ln == 127:
                while len(buf) < 10:
                    buf += s.recv(65536)
                ln = struct.unpack(">Q", buf[2:10])[0]
                off = 10
            while len(buf) < off + ln:
                buf += s.recv(65536)
            return json.loads(buf[off:off + ln].decode())

        mid = [0]

        def call(method, **params):
            mid[0] += 1
            send({"id": mid[0], "method": method, "params": params})
            while True:
                msg = recv()
                if msg.get("id") == mid[0]:
                    return msg

        def js(expr):
            r = call("Runtime.evaluate", expression=expr,
                     awaitPromise=True, returnByValue=True)
            return r.get("result", {}).get("result", {}).get("value")

        call("Page.enable")
        call("Runtime.enable")
        q = urllib.parse.quote
        page = sys.argv[3] if len(sys.argv) > 3 else "create"
        target = ("http://127.0.0.1:8788/studio/?theme=dark&ws=%s&doc=plan#/%s"
                  % (q(ws_path, safe=""), page))
        call("Page.navigate", url=target)
        # 等创作页把文档读完（有 #edText 说明编辑器已就位）
        click = sys.argv[4] if len(sys.argv) > 4 else "#edVers"
        wait_for = sys.argv[5] if len(sys.argv) > 5 else "#edText"
        for _ in range(60):
            if js('!!document.querySelector(%s)' % json.dumps(wait_for)):
                break
            time.sleep(0.5)
        time.sleep(1.2)

        print("目标元素存在:", js("!!document.querySelector(%s)" % json.dumps(click)))
        print("当前页:", js("location.hash"))
        # 把未捕获异常记下来 —— openVersions 里抛错不会出现在截图上
        js("window.__err=[];window.addEventListener('error',e=>window.__err.push(String(e.message)));"
           "window.addEventListener('unhandledrejection',e=>window.__err.push(String(e.reason&&e.reason.message||e.reason)));")
        # 支持多步点击：selector1 ;; selector2（先切变体再点重出这类两段动作）
        for one in click.split(";;"):
            one = one.strip()
            if not one:
                continue
            hit = js("!!document.querySelector(%s)" % json.dumps(one))
            js("document.querySelector(%s) && document.querySelector(%s).click()" % (json.dumps(one), json.dumps(one)))
            time.sleep(0.5)
            print("  点击 %-46s 命中=%s 当前选中=%s" % (
                one, hit,
                js("(document.querySelector('.sd-ctab.on')||{dataset:{}}).dataset.cv || '-'")))
        for _ in range(40):
            if js("!!document.querySelector('.modal.on')"):
                break
            time.sleep(0.3)
        time.sleep(0.8)

        shot = call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        data = shot["result"]["data"]
        pathlib.Path(out).write_bytes(base64.b64decode(data))
        print("saved", out)
        print("diff 行统计:", js(
            "JSON.stringify({add:document.querySelectorAll('.sd-vd-line.add').length,"
            "del:document.querySelectorAll('.sd-vd-line.del').length,"
            "lines:document.querySelectorAll('.sd-vd-line').length})"))
        print("弹窗宽度:", js("document.querySelector('#modal').offsetWidth"))
        print("弹窗标题:", js("document.getElementById('modalTitle').textContent"))
        print("弹窗宽版类:", js("document.querySelector('#modal').className"))
        print("弹窗正文前 400:", (js("document.getElementById('modalBody').innerText") or "")[:400])
        print("捕获到的异常:", js("JSON.stringify(window.__err||[])"))
        print("选中变体:", js("(document.querySelector('.sd-ctab.on')||{}).dataset && document.querySelector('.sd-ctab.on').dataset.cv"))
        print("图片区 key:", js("(document.querySelector('.sd-cstage-bar .mono')||{}).textContent"))
        print("图张数:", js("document.querySelectorAll('.sd-cstage-body img').length"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    main()
