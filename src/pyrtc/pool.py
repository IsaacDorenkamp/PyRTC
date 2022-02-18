import asyncio
import inspect
import uuid

from .transceiver import Transceiver, TransceiverManager

class Pool:
	"""
	Represents a WebRTC connection pool.
	"""

	def __init__(self, name, is_async=False):
		"""
		Create a pool with the given unique name.

		:param name: The pool's unique name.
		:param is_async: Whether the pool uses async/await.
		  Note that async Pools can only be added to async
		  PoolManagers and non-async Pools can only be
		  added to non-async PoolManagers.
		"""
		self._name = name
		self._conns = {}
		self._closed = False
		self._async = is_async

	def get_peer_ids(self):
		"""
		:returns: A tuple of the IDs of all connected peers.
		:rtype: tuple
		"""
		return tuple(self._conns.keys())

	@property
	def name(self):
		"""
		The pool's unique name.
		"""
		return self._name

	@property
	def closed(self):
		"""
		Whether this pool has been closed.
		"""
		return self._closed

	def allows(self, endpoint):
		"""
		A method which returns a boolean
		value telling whether the given
		endpoint is allowed to join this
		pool. Subclasses may return False
		in some cases, blocking certain
		endpoints from joining.
		"""
		return not self.closed

	def get_connection(self, test):
		"""
		If test is a string, gets a connection by its ID.
		If test is a Transceiver, gets the connection associated with it.
		If no connection is found, None is returned.

		:param test: The unique ID or transceiver associated with the desired connection.
		:returns: A dictionary with keys 'socket' (a Transceiver instance), 'id' (the
		  unique ID), and 'description' (the description of the endpoint).
		"""
		if isinstance(test, str):
			return self._conns.get(test, None)
		elif isinstance(test, Transceiver):
			for i in self._conns.values():
				if i['socket'] == test:
					return i
			return None
		else:
			raise TypeError("get_connection accepts a UUID string or a Transceiver.")

	def add_endpoint(self, transceiver):
		"""
		Accepts a Transceiver and adds it to the pool as an endpoint.
		"""
		if transceiver in self:
			raise ValueError("This endpoint has already been added!")

		if self.allows(transceiver):
			peers = self.get_peer_ids()

			ent = {
				'socket': transceiver,
				'id': str(uuid.uuid4()),
				'description': None
			}

			self._conns[ent['id']] = ent
			transceiver.id = ent['id']

			yield (transceiver, 'rtc:joined', {
				'client_id': ent['id'],
				'peers': peers,
				'descriptions': dict(map(lambda entry: (entry['id'], entry['description']), self._conns.values())),
				'pool': self.name
			})

			yield from map(lambda conn: (conn['socket'], 'rtc:peer', {
				'id': transceiver.id
			}), filter(lambda conn: conn['id'] != transceiver.id, self._conns.values()))

		else:
			yield (transceiver, 'rtc:error', {
				'message': 'Could not join pool.'
			})

	def update(self):
		"""
		Prunes closed connections and notifies peers of the closure.
		"""
		if self.closed: return

		# remove closed transceivers,
		# send close notifications to peers
		pre_load = tuple(self._conns.values())
		closed = []
		for conn in pre_load:
			if not conn['socket'].is_open():
				closed.append(conn['id'])
				del self._conns[conn['id']]

		futs = []
		for c in closed:
			# include uid and id to support RTCPool 3.0.0 and 3.0.1
			# (3.0.0 still uses uid as a holdover from the previous protocol)
			futs.append(self.broadcast('rtc:close', { 'uid': c, 'id': c }))

		if self._async:
			return asyncio.gather(*futs)

	def describe(self, test, desc):
		"""
		Sets the description of the specified connection.

		:param test: The unique ID or Transceiver identifying
		  the peer connection
		:param desc: The description to assign to the specified
		  endpoint. Must be a JSON-serializable dictionary or None.
		"""
		if self.closed:
			raise ValueError("Pool is closed")

		assert desc is None or isinstance(desc, dict)
		conn = self.get_connection(test)
		if conn:
			conn['description'] = desc
			return self.broadcast('rtc:describe', {
				'description': desc,

				# Holdover of old protocol from RTCPool 3.0.0,
				# fixed in version 3.0.1
				'uid': conn['id'],
				'id': conn['id']
			}, conn['socket'])
		else:
			raise ValueError(f"No connection associated with {test}")

	def broadcast(self, evt_type, evt_data, *exclude):
		"""
		Broadcasts the specified event to all connections in the pool,
		except for those whose Transceiver is in ``exclude``.

		:param evt_type: The type of event to broadcast to the peers.
		:type evt_type: str
		:param evt_data: The event data.
		:type evt_data: dict
		"""
		if self.closed:
			raise ValueError("Pool is closed")

		res = []
		for conn in filter(lambda ent: ent['socket'] not in exclude, self._conns.values()):
			res.append(conn['socket'].send(evt_type, evt_data))

		if self._async:
			return asyncio.gather(*res)

	def close(self):
		"""
		Sends a signal to close all connections in the pool,
		and closes the signalling channels.
		"""

		if self.closed:
			raise ValueError("Pool is closed")

		if self._async:
			return self._close_async()
		else:
			self.broadcast('rtc:stop', {})
			for conn in self._conns.values():
				conn['socket'].close()

			self._conns.clear()
			self._closed = True

	async def _close_async(self):
		await self.broadcast('rtc:stop', {})
		await asyncio.gather(*map(lambda conn: conn['socket'].close(), self._conns.values()))

		self._conns.clear()
		self._closed = True

	def __contains__(self, test):
		if isinstance(test, str):
			# check by UID
			return test in self._conns.keys()
		elif isinstance(test, Transceiver):
			return test in map(lambda ent: ent['socket'], self._conns.values())
		else:
			return False

def _flatten(two_deep_gen):
	for gen in two_deep_gen:
		if gen is not None:
			yield from gen

class PoolManager:
	"""
	A class responsible for managing multiple pools.
	An endpoint that wants access to the pool must
	be added to the PoolManager containing that pool
	in order to join it.
	"""
	def __init__(self, private=True, is_async=False):
		"""
		Create a pool manager.

		:param private: Whether the pool manager is "private."
		  Private pool managers will send error messages to
		  clients seeking to join a pool that doesn't exist,
		  while public pool managers will automatically create
		  a pool and add the endpoint to it if such a pool does
		  not exist.
		:type private: bool

		:param is_async: Whether this pool is asynchronous, that is,
		  meant for use with Transceivers whose send, receive, and close
		  methods are asynchronous.
		:type is_async: bool
		"""
		self._private = private
		self._pools = []
		self._trans = TransceiverManager(is_async=is_async)

		self._async = is_async
		self._closed = False

	def close(self):
		"""
		Closes this pool manager.
		"""
		res = self._trans.close_all()
		self._closed = True
		if self._async:
			return res # a result of asyncio.gather

	def _close_assert(self, msg="PoolManager is closed"):
		assert not self._closed, msg

	def update(self):
		"""
		Handles all messages from clients. Should be
		called soon after new data is available from
		any endpoint handled by this pool manager.
		"""
		self._close_assert()
		if self._async:
			return self._update_async()
		else:
			for event, source in self._trans.events():
				messages = self.handle_event(event, source)
				self._sendall(messages)

			self.cleanup()

	async def _update_async(self):
		futs = []
		async for event, source in self._trans.events():
			messages = self.handle_event(event, source)
			futs.extend(self._sendall(messages))

		await asyncio.gather(*futs)
		await self.cleanup()

	def _sendall(self, messages):
		futs = []
		for message in messages:
			futs.append(message[0].send(*message[1:]))
		return futs

	def cleanup(self):
		immut = tuple(self._pools)
		futs = []
		for pool in immut:
			if pool.closed:
				self._pools.remove(pool)
			else:
				futs.append(pool.update())

		if self._async:
			return asyncio.gather(*futs)

	def add_endpoint(self, transceiver):
		"""
		Adds an endpoint to this PoolManager. This means
		that this PoolManager will now handle all events
		received from the given endpoint:

		:param transceiver: The transceiver representing the connection
		  to an endpoint.
		:type transceiver: Transceiver
		"""
		self._close_assert()

		if transceiver.is_async and not self._async:
			raise ValueError("Cannot add asynchronous transceiver to non-async PoolManager")
		elif not transceiver.is_async and self._async:
			# TODO: 'asyncify'
			raise ValueError("Cannot add non-async transceiver to async PoolManager")

		self._trans.dispatch(transceiver)

	def add_pool(self, pool):
		"""
		Adds a pool to the list of available pools
		in this PoolManager.

		:param pool: The pool to add.
		:type pool: Pool
		"""
		self._close_assert()
		if pool.name in map(lambda pool: pool.name, self._pools):
			raise ValueError(f"Pool with name '{pool.name}' already exists!")
		else:
			self._pools.append(pool)

	def get_pool(self, name):
		"""
		Gets a pool by name.

		:param name: The name of the pool to get.
		:type name: str
		:returns: The pool with the given name, or
		  None if it does not exist.
		:rtype: Pool or None
		"""
		for pool in self._pools:
			if pool.name == name: return pool

		return None

	def remove_pool(self, name):
		"""
		Removes a pool from this manager. When calling this,
		be sure the pool has been closed, as this method does
		not do this automatically.

		:param name: The name of the pool to close.
		:type name: str
		:returns: True if the pool exists and was removed,
		  False otherwise.
		:rtype: bool
		"""
		self._close_assert()
		pool = self.get_pool(name)
		if pool is not None:
			self._pools.remove(pool)
			return True
		else:
			return False

	def _query(self, test):
		for pool in self._pools:
			conn = pool.get_connection(test)
			if conn:
				return pool, conn

		return None, None

	def get_pool_for(self, test):
		"""
		Gets a pool by a connection identifier,
		either the Transceiver associated with
		an endpoint or the connection ID.

		:param test: The Transceiver or connection ID.
		:type test: Transceiver or str

		:returns: The pool if one exists, otherwise None.
		:rtype: Pool or None
		"""
		return self._query(test)[0]

	def get_connection_for(self, test):
		"""
		Like :meth:`get_pool_for`, but returns the connection
		information as a dict.

		:param test: The Transceiver or connection ID.
		:type test: Transceiver or str

		:returns: The connection information if it exists, otherwise None.
		:rtype: dict or None
		"""
		return self._query(test)[1]

	def handle_event(self, event, source):
		"""
		Handles a single event from the
		specified source, returning a list
		of messages and endpoints that should
		be sent in response to the event.

		:param: event
		:type event: tuple
		:param source:
		:type source: Transceiver

		:returns: An iterator that provides tuples in the format
			(destination, event_type, event_data) where destination
			is a :class:`Transceiver`, event_type is a str, and
			event_data is a dict
		:rtype: iter<tuple>
		"""

		self._close_assert()

		messages = ()

		name, data = event
		parts = name.split(':')
		prefix = parts[0]
		if prefix != 'rtc' or len(parts) != 2:
			# Ignore events not intended for the rtc
			# signalling process. This allows a single
			# websocket to be used for RTC signalling
			# as well as other applications.
			return messages

		action = parts[1]
		if action == 'join':
			_pool = data.get('pool', None)
			if not _pool:
				return (source, 'rtc:error', {
					'message': 'Please specify a pool to join.'
				})
			pool = self.get_pool(_pool)

			if pool:
				messages = pool.add_endpoint(source)
			else:
				if self._private:
					# pools cannot be created implicitly,
					# must be explicitly created by server code
					return (source, 'rtc:error', {
						'message': 'No such pool exists.',
						'pool': _pool
					})
				else:
					# auto-add default pool
					pool = Pool(_pool, is_async=self._async)
					self.add_pool(pool)
					messages = pool.add_endpoint(source)
		elif action == 'sdp':
			target = data.get('to', None)
			conn = self.get_connection_for(target)
			if conn:
				messages = ((conn['socket'], 'rtc:sdp', {
					'peer': source.id,
					'description': data.get('description', None)
				}),)
			else:
				messages = ((source, 'rtc:error', {
					'message': 'Please specify a valid answer target.'
				}),)
		elif action == 'candidate':
			target = data.get('for', None)
			if target:
				conn = self.get_connection_for(target)
				if conn:
					messages = ((conn['socket'], 'rtc:candidate', {
						'candidate': data.get('candidate'),
						'from': source.id
					}),)
			else:
				messages = ((source, 'rtc:error', {
					'message': "Please specify a candidate recipient in the 'for' field."
				}),)
		else:
			messages = ((source, 'rtc:error', {
				'message': f"RTC action '{action}' not recognized."
			}),)

		return iter(messages)