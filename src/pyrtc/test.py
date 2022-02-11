from contextlib import contextmanager
import functools

import select
import socket

from . import transport, transceiver, pool

def can_accept(serv_sock):
	return serv_sock in select.select([serv_sock], [], [], 0)[0]

@contextmanager
def clean_exit(cleanup, *ignore_exc):
	try:
		yield None
	except BaseException as exc:
		# catch BaseException to include
		# non-error Exceptions such as KeyboardInterrupt
		if not any([isinstance(exc, exc_type) for exc_type in ignore_exc]):
			raise
	finally:
		cleanup()

def close(*args):
	for arg in args: arg.close()

class sockmanager:
	def __init__(self):
		self._socks = []

	def __iter__(self):
		self.update()
		return iter(self._socks)

	def update(self):
		self._socks[:] = [sock for sock in self._socks if sock.open or sock.receiver.pending > 0]

	def put(self, sock):
		self._socks.append(sock)

def main(port=7001):
	pools = pool.PoolManager(False)
	serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	serv.bind(('0.0.0.0', port))
	serv.setblocking(0)
	serv.listen(5)

	mgr = sockmanager()

	import time
	with clean_exit(functools.partial(close, serv, pools), KeyboardInterrupt):
		while True:
			while can_accept(serv):
				conn, addr = serv.accept()
				trans = transceiver.WebsocketTransceiver.of(conn)
				wsock = trans.socket
				wsock.receiver = transport.EventReceiver()
				wsock.transceiver = trans
				wsock.add_receiver(wsock.receiver)
				mgr.put(wsock)
				pools.add_endpoint(trans)

			pools.update()

			for sock in mgr:
				for name, data in sock.receiver:
					if name == "describe":
						sp = pools.get_pool_for(sock.transceiver)
						sp.describe(sock.transceiver, data)
		
			time.sleep(.01)

class AsyncWebsocketTransceiver(transceiver.WebsocketTransceiver):
	is_async = True

	async def receive(self):
		for msg in super().receive():
			yield msg

	async def send(self, event_type, event_data):
		super().send(event_type, event_data)

	async def close(self):
		super().close()

	@staticmethod
	def of(raw_sock):
		porter = transport.Websocket(raw_sock)
		return AsyncWebsocketTransceiver(porter)

async def main_async(port=7001):
	pools = pool.PoolManager(False, is_async=True)
	serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	serv.bind(('0.0.0.0', port))
	serv.setblocking(0)
	serv.listen(5)

	mgr = sockmanager()

	import time
	with clean_exit(functools.partial(close, serv, pools), KeyboardInterrupt):
		while True:
			while can_accept(serv):
				conn, addr = serv.accept()
				trans = AsyncWebsocketTransceiver.of(conn)
				wsock = trans.socket
				wsock.receiver = transport.EventReceiver()
				wsock.transceiver = trans
				wsock.add_receiver(wsock.receiver)
				mgr.put(wsock)
				pools.add_endpoint(trans)

			await asyncio.sleep(0.01)
			await pools.update()

			for sock in mgr:
				for name, data in sock.receiver:
					if name == "describe":
						sp = pools.get_pool_for(sock.transceiver)
						await sp.describe(sock.transceiver, data)

if __name__ == '__main__':
	import sys

	test_type = "sync"
	if len(sys.argv) > 1:
		test_type = sys.argv[1]

	if test_type == "async":
		print("Running async test")

		import asyncio
		asyncio.run(main_async())
	elif test_type == "sync":
		print("Running sync test")
		main()
	else:
		print(f"No such test '{test_type}.")