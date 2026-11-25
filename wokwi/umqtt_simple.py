"""Cliente MQTT ligero para MicroPython (compatible con v1.20+).

Basado en umqtt.simple e incluido localmente en wokwi/ para garantizar
portabilidad sin depender de descargas en tiempo de ejecución en Wokwi.
Soporta Last Will & Testament (LWT), keepalive, QoS 0/1, retain, ping y
recepción no bloqueante mediante check_msg().
"""

try:
    import usocket as socket
except ImportError:
    import socket

try:
    import ustruct as struct
except ImportError:
    import struct

import time


class MQTTException(Exception):
    """Excepción específica para errores del protocolo MQTT."""


def _to_bytes(val):
    """Convierte str a bytes UTF-8 si es necesario."""
    if isinstance(val, str):
        return val.encode("utf-8")
    return val


class MQTTClient:
    """Implementación minimalista de cliente MQTT 3.1.1 para MicroPython."""

    def __init__(
        self,
        client_id,
        server,
        port=0,
        user=None,
        password=None,
        keepalive=0,
        ssl=False,
        ssl_params=None,
    ):
        if port == 0:
            port = 8883 if ssl else 1883
        self.client_id = _to_bytes(client_id)
        self.sock = None
        self.server = server
        self.port = port
        self.ssl = ssl
        self.ssl_params = ssl_params or {}
        self.pid = 0
        self.cb = None
        self.user = _to_bytes(user) if user is not None else None
        self.pswd = _to_bytes(password) if password is not None else None
        self.keepalive = keepalive
        self.lw_topic = None
        self.lw_msg = None
        self.lw_qos = 0
        self.lw_retain = False

    def _send_str(self, data):
        data = _to_bytes(data)
        self.sock.write(struct.pack("!H", len(data)))
        self.sock.write(data)

    def _recv_len(self):
        n = 0
        sh = 0
        while True:
            b = self._read_exact(1)[0]
            n |= (b & 0x7F) << sh
            if not (b & 0x80):
                return n
            sh += 7

    def _read_exact(self, n):
        """Lee exactamente n bytes del socket, fallando si la conexión se cierra."""
        if n == 0:
            return b""
        buf = bytearray()
        espera = 0
        while len(buf) < n:
            chunk = self.sock.read(n - len(buf))
            if chunk is None:
                espera += 1
                if espera > 1000:
                    raise OSError(-1)
                if hasattr(time, "sleep_ms"):
                    time.sleep_ms(5)
                else:
                    time.sleep(0.005)
                continue
            if len(chunk) == 0:
                raise OSError(-1)
            espera = 0
            buf.extend(chunk)
        return bytes(buf)

    def _encode_remaining_length(self, pkt, sz):
        while True:
            digit = sz & 0x7F
            sz >>= 7
            if sz:
                digit |= 0x80
            pkt.append(digit)
            if not sz:
                break

    def set_callback(self, f):
        """Registra la función callback(topic, msg) para mensajes recibidos."""
        self.cb = f

    def set_last_will(self, topic, msg, retain=False, qos=0):
        """Configura el mensaje Last Will & Testament antes de conectar."""
        assert 0 <= qos <= 2
        assert topic
        self.lw_topic = _to_bytes(topic)
        self.lw_msg = _to_bytes(msg)
        self.lw_qos = qos
        self.lw_retain = retain

    def connect(self, clean_session=True, timeout=10):
        """Establece la conexión TCP y realiza el handshake CONNECT/CONNACK."""
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        self.sock = socket.socket()
        if timeout is not None and hasattr(self.sock, "settimeout"):
            self.sock.settimeout(timeout)
        self.sock.connect(addr)

        if self.ssl:
            import ussl
            self.sock = ussl.wrap_socket(self.sock, **self.ssl_params)

        premsg = bytearray(b"\x10\0\0\0\0\0")
        msg = bytearray(b"\x00\x04MQTT\x04\x02\0\0")

        sz = 10 + 2 + len(self.client_id)
        msg[7] = clean_session << 1
        if self.user is not None:
            sz += 2 + len(self.user)
            msg[7] |= 0x80
            if self.pswd is not None:
                sz += 2 + len(self.pswd)
                msg[7] |= 0x40

        if self.keepalive:
            assert self.keepalive < 65536
            msg[8] |= self.keepalive >> 8
            msg[9] |= self.keepalive & 0x00FF

        if self.lw_topic is not None:
            sz += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
            msg[7] |= 0x04 | ((self.lw_qos & 0x01) << 3) | ((self.lw_qos & 0x02) << 3)
            msg[7] |= (1 if self.lw_retain else 0) << 5

        i = 1
        while sz > 0x7F:
            premsg[i] = (sz & 0x7F) | 0x80
            sz >>= 7
            i += 1
        premsg[i] = sz

        self.sock.write(premsg[: i + 1])
        self.sock.write(msg)
        self._send_str(self.client_id)
        if self.lw_topic is not None:
            self._send_str(self.lw_topic)
            self._send_str(self.lw_msg)
        if self.user is not None:
            self._send_str(self.user)
            if self.pswd is not None:
                self._send_str(self.pswd)

        resp = self._read_exact(4)
        if resp[0] != 0x20 or resp[1] != 0x02:
            raise MQTTException("CONNACK inválido")
        if resp[3] != 0:
            raise MQTTException(resp[3])
        return resp[2] & 1

    def disconnect(self):
        """Envía DISCONNECT y cierra el socket limpio."""
        try:
            if self.sock is not None:
                self.sock.write(b"\xe0\x00")
        finally:
            if self.sock is not None:
                self.sock.close()
                self.sock = None

    def ping(self):
        """Envía paquete PINGREQ para mantener activa la sesión keepalive."""
        self.sock.write(b"\xc0\x00")

    def publish(self, topic, msg, retain=False, qos=0):
        """Publica un mensaje en el tema indicado."""
        topic = _to_bytes(topic)
        msg = _to_bytes(msg)
        pkt = bytearray(b"\x30")
        pkt[0] |= (qos << 1) | (1 if retain else 0)
        sz = 2 + len(topic) + len(msg)
        if qos > 0:
            sz += 2
        assert sz < 2097152
        self._encode_remaining_length(pkt, sz)
        self.sock.write(pkt)
        self._send_str(topic)
        if qos > 0:
            self.pid += 1
            if self.pid > 65535:
                self.pid = 1
            pid = self.pid
            self.sock.write(struct.pack("!H", pid))
        self.sock.write(msg)

        if qos == 1:
            intentos = 0
            while True:
                op = self.wait_msg()
                if op is None:
                    intentos += 1
                    if intentos > 500:
                        raise OSError(-1)
                    time.sleep_ms(10)
                    continue
                if op == 0x40:
                    sz_ack = self._read_exact(1)
                    if sz_ack != b"\x02":
                        raise MQTTException("PUBACK inválido")
                    rcv_pid = struct.unpack("!H", self._read_exact(2))[0]
                    if pid == rcv_pid:
                        return
        elif qos == 2:
            raise MQTTException("QoS 2 no soportado")

    def subscribe(self, topic, qos=0):
        """Suscribe el cliente a un tema MQTT."""
        assert self.cb is not None, "Debe configurar set_callback antes de suscribirse"
        topic = _to_bytes(topic)
        self.pid += 1
        if self.pid > 65535:
            self.pid = 1
        pid = self.pid
        pkt = bytearray(b"\x82")
        sz = 2 + 2 + len(topic) + 1
        self._encode_remaining_length(pkt, sz)
        self.sock.write(pkt)
        self.sock.write(struct.pack("!H", pid))
        self._send_str(topic)
        self.sock.write(bytes([qos]))
        intentos = 0
        while True:
            op = self.wait_msg()
            if op is None:
                intentos += 1
                if intentos > 500:
                    raise OSError(-1)
                time.sleep_ms(10)
                continue
            if op == 0x90:
                resp = self._read_exact(4)
                if resp[1] != (pid >> 8) or resp[2] != (pid & 0xFF):
                    raise MQTTException("SUBACK PID no coincide")
                if resp[3] == 0x80:
                    raise MQTTException("Suscripción rechazada por broker")
                return

    def wait_msg(self):
        """Espera y procesa un paquete entrante del broker."""
        res = self.sock.read(1)
        if res is None:
            return None
        if res == b"":
            raise OSError(-1)

        # Garantiza lectura completa del resto de la trama aunque check_msg esté en no bloqueante
        if hasattr(self.sock, "settimeout"):
            self.sock.settimeout(5)

        if res == b"\xd0":  # PINGRESP
            sz = self._read_exact(1)[0]
            assert sz == 0
            return None

        op = res[0]
        if op & 0xF0 != 0x30:
            return op

        sz = self._recv_len()
        topic_len = struct.unpack("!H", self._read_exact(2))[0]
        topic = self._read_exact(topic_len)
        sz -= topic_len + 2
        pid = None
        if op & 0x06:
            pid = struct.unpack("!H", self._read_exact(2))[0]
            sz -= 2
        msg = self._read_exact(sz)
        if self.cb is not None:
            self.cb(topic, msg)
        if (op & 0x06) == 0x02:
            pkt = bytearray(b"\x40\x02\0\0")
            struct.pack_into("!H", pkt, 2, pid)
            self.sock.write(pkt)
        elif (op & 0x06) == 0x04:
            raise MQTTException("QoS 2 entrante no soportado")
        return op

    def check_msg(self):
        """Comprueba si hay mensajes entrantes sin bloquear el bucle principal."""
        self.sock.setblocking(False)
        try:
            return self.wait_msg()
        except OSError as err:
            # EAGAIN / EWOULDBLOCK en sockets no bloqueantes simplemente indica sin datos
            if err.args and err.args[0] in (11, 110, 115):
                return None
            raise
        finally:
            if self.sock is not None and hasattr(self.sock, "settimeout"):
                self.sock.settimeout(5)
