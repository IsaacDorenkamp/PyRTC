import json

import select
import socket
import ssl

from wsproto import events, ConnectionType, WSConnection
from wsproto.connection import ConnectionState

def can_read(sock):
	if isinstance(sock, ssl.SSLSocket):
		return sock.pending() > 0
	else:
		return sock in select.select([sock], [], [], 0)[0]

def can_write(sock):
	# should work for both SSL and non-SSL sockets
	return sock in select.select([], [sock], [], 0)[1]

def create_event(name, data):
	return events.TextMessage(json.dumps({
		'type': name,
		'data': data
	}))

class EventReceiver:
	"""
	A helper class to allow multiple
	targets receive events from :class:`Websocket`
	"""
	def __init__(self):
		self._buffer = []

	def __iter__(self):
		return self

	def __next__(self):
		"""
		Gets the next event in the buffer,
		otherwise raises StopIteration
		"""
		if len(self._buffer) > 0:
			return self._buffer.pop(0)
		else:
			raise StopIteration

	def post(self, evt):
		"""
		Add an event to the buffer.
		"""
		self._buffer.append(evt)

	@property
	def pending(self):
		"""
		True if there are events in
		the buffer, False otherwise

		:type: bool
		"""
		return len(self._buffer)

class Websocket:
	"""
	A class that wraps a socket and
	transmits data over it through
	the WebSocket protocol defined
	in :RFC:`6455`.
	"""
	def __init__(self, cli_sock):
		"""
		Creates a WebSocket connection
		over the given socket.

		:param cli_sock: The socket to send data through.
		:type cli_sock: socket
		"""
		self._sock = cli_sock
		self._conn = WSConnection(ConnectionType.SERVER)
		self._closed = False
		self._receivers = []

	def add_receiver(self, receiver):
		"""
		Adds a target for received events.

		:param receiver: The event target.
		:type receiver: EventReceiver
		"""
		if isinstance(receiver, EventReceiver):
			self._receivers.append(receiver)
		else:
			raise TypeError("receiver must be an instance of EventReceiver")

	def _raw_send(self, data):
		if self._sock.fileno() == -1:
			self._closed = True
			return

		sent = 0
		while sent < len(data):
			if can_write(self._sock):
				try:
					sent += self._sock.send(data[sent:])
				except socket.error:
					# broken pipe
					self._closed = True
					return
			else:
				time.sleep(0.05)

	@property
	def open(self):
		"""
		Whether the connection is open.

		:type: bool
		"""
		return self._conn.state == ConnectionState.OPEN and not self._closed

	def close(self, status=1000):
		"""
		Closes the WebSocket connection with the specified status
		(1000, the all-ok status code for WebSocket closure)

		:param status: The status code to close with.
		:type status: int
		"""
		if self._conn.state != ConnectionState.OPEN:
			raise ValueError("WebSocket not in the OPEN state.")
		else:
			close = self._conn.send(events.CloseConnection(status))
			self._raw_send(close)
			self._sock.close()

	def close_raw(self):
		"""
		A safe close function that will cleanly close
		the socket if the WebSocket connection state is
		not open.
		"""
		if self._conn.state == ConnectionState.OPEN:
			self.close()
		else:
			self._closed = True
			self._sock.close()

	def send(self, data):
		"""
		Send data over the WebSocket connection.
		May be a str or bytes, but the ws.proto
		Message counterparts are accepted as well.
		"""
		if isinstance(data, str):
			message = events.TextMessage(data)
		elif isinstance(data, bytes):
			message = events.BytesMessage(data)
		elif isinstance(data, (events.TextMessage, events.BytesMessage)):
			message = data
		else:
			raise TypeError("message must be a str or bytes object, or a TextMessage/BytesMessage")

		raw_data = self._conn.send(message)
		self._raw_send(raw_data)

	def receive(self):
		"""
		Receives all available data from
		socket, then posts all all events
		to all added receivers.
		"""
		if self._closed:
			return

		while can_read(self._sock):
			data = self._sock.recv(2048)
			if not data:
				# socket closed
				self._closed = True
				return
			self._conn.receive_data(data)

		for event in self._handle(self._conn.events()):
			for recv in self._receivers:
				recv.post(event)

	def _handle(self, event_iter):
		for event in event_iter:
			if isinstance(event, events.Request):
				self._raw_send(self._conn.send(events.AcceptConnection()))
			elif isinstance(event, events.TextMessage):
				if event.message_finished:
					try:
						evt_data = json.loads(event.data)
					except json.decoder.JSONDecodeError:
						# tell client to send valid data!
						self._raw_send(self._conn.send(create_event('rtc:error', { 'message': 'Please send valid JSON data.' })))

					name = evt_data.get('type', None)
					data = evt_data.get('data', None)
					if not (name and isinstance(data, dict)):
						self._raw_send(self._conn.send(create_event('rtc:error', { 'message': 'Please send an event with "type" and "data" fields.' })))
					else:
						yield (name, data)
			elif isinstance(event, events.Ping):
				# send pong, nothing to yield
				self._raw_send(self._conn.send(event.response()))
			elif isinstance(event, events.CloseConnection):
				self.close_raw()
				return
			else:
				# ignore all else
				pass