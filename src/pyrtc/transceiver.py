from abc import ABC, abstractmethod
import asyncio

from . import transport

class Transceiver(ABC):
	"""
	Abstract base class for all transceivers.
	"""

	is_async = False

	def __init__(self):
		self.id = None

	@abstractmethod
	def is_open(self):
		"""
		A method used to check whether the channel
		used to transmit and received data is open.
		"""
		return True

	@abstractmethod
	def send(self, event_type, event_data):
		"""
		A method which sends an event to an endpoint. How the
		data is sent or formatted is defined by individual
		subclasses and is not important as long as it sent somehow.

		:param event_type: The type of event to be processed.
		:type event_type: str
		:param event_data: Data describing the event.
		:type event_data: dict
		"""
		pass

	@abstractmethod
	def receive(self):
		"""
		A generator yielding all relevant events at the time it is called.

		Events should be yielded as a 2-tuple (event_type, event_data)
		"""
		pass

	@abstractmethod
	def close(self):
		"""
		Close the connection used for sending and receiving data.
		"""
		pass

class WebsocketTransceiver(Transceiver):
	def __init__(self, ws):
		super().__init__()
		if not isinstance(ws, transport.Websocket):
			raise TypeError("ws must be a Websocket instance!")
		else:
			self._ws = ws
			self._recv = transport.EventReceiver()
			self._ws.add_receiver(self._recv)

	def is_open(self):
		"""
		:returns: True if the Websocket is open, False otherwise
		:rtype: bool
		"""
		return self._ws.open

	def send(self, event_type, event_data):
		"""
		Sends an event via the Websocket.

		:param event_type: The type of event to be processed.
		:type event_type: str
		:param event_data: Data describing the event.
		:type event_data: dict
		"""
		self._ws.send(transport.create_event(event_type, event_data))

	def receive(self):
		"""
		Receives data from Websocket, and yields events as 2-tuples
		(as described by :class:`Transceiver`)
		"""
		self._ws.receive()
		yield from self._recv

	def close(self):
		"""
		Close the connection to the Websocket.
		"""
		self._ws.close_raw()

	@property
	def socket(self):
		"""
		The Websocket instance used by this
		instance to send and receive data.
		"""
		return self._ws

	@staticmethod
	def of(raw_sock):
		"""
		Create a WebSocket transceiver from a
		raw socket. This could be a plain socket
		or one wrapped in an SSL context.

		:param raw_sock: The socket to create a
		  WebsocketTransceiver around.
		:returns: A WebsocketTransceiver that sends
		  data over a Websocket connection through
		  raw_sock.
		"""
		porter = transport.Websocket(raw_sock)
		return WebsocketTransceiver(porter)

class TransceiverManager:
	"""
	A helper class used by :class:`Pool` to
	aggregate events from transceivers and
	easily close down all connections at once.
	"""
	def __init__(self, is_async=False):
		self._trans = []
		self._async = is_async

	def dispatch(self, transceiver):
		"""
		Adds a transceiver to this manager instance.
		"""
		self._trans.append(transceiver)

	def events(self):
		"""
		Used by PoolManager to receive all events from all
		transceivers and handle them.
		"""
		if self._async:
			return self._async_events()
		else:
			return self._sync_events()

	def _sync_events(self):
		for trans in self._trans:
			for event in trans.receive():
				yield (event, trans)

		self._trans[:] = [trans for trans in self._trans if trans.is_open()]
	
	async def _async_events(self):
		for trans in self._trans:
			async for event in trans.receive():
				yield (event, trans)

		self._trans[:] = [trans for trans in self._trans if trans.is_open()]

	def close_all(self):
		"""
		Close all transcievers.
		"""
		futs = []
		for trans in self._trans:
			futs.append(trans.close())

		self._trans[:] = []

		if self._async:
			return asyncio.gather(*futs)
