Quickstart
==========

Installation
------------

To install pyrtc, simply use pip::

	$ pip install pyrtc

A Simple Back-End
-----------------

PyRTC is essentially a pre-packaged WebRTC signalling back-end
with a Pythonic, object-oriented approach that leaves a lot of
flexibility for developers trying to build real-time communication
applications using WebRTC. Here, I will provide a summary of the
included ``pyrtc.test`` module, a fully-functional test server that
uses the WebSocket protocol for data transfer, and demonstrate
the creation of a simple JavaScript application using a client-side
library that I also wrote using the same event-based negotiation
scheme as PyRTC. Let's begin with the first lines of ``main`` in
test.py::

	pools = pool.PoolManager(False)
	serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	serv.bind(('0.0.0.0', port))
	serv.setblocking(0)
	serv.listen(5)

These lines are largely straightforward: here, we are creating
a PoolManager with private set to False, as for testing, we want
to automatically create a pool if one does not exist. The lines after
that are pretty boilerplate, setting up a server socket with an
added line to tell the socket that the address should be reusable
so that if you were to stop and restart the program, there would
be no TIME_WAIT on the underlying TCP layer preventing the socket
from binding to 0.0.0.0 on the specified port for a significant period
of time. Next::

	mgr = sockmanager()

	import time
	with clean_exit(functools.partial(close, serv, pools), KeyboardInterrupt):
		...

sockmanager is a helper class defined earlier in test.py that allows us
to add Websockets to it (which we use in the later lines to loop through
all connected Websockets and handle our own custom event from the
WebSocket), and 'clean_exit' is a helper context manager used to automatically
clean up resources and cleanly exit on an error or KeyboardInterrupt. These are
not important for understanding the more relevant concepts. The meat and
potatoes of our code begins here::

	with ...:
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

Above is our mainloop. We loop forever (until KeyboardInterrupt, that is),
and in each iteration, we check if we can accept new connections. If we can,
we accept them and create a :class:`WebsocketTransceiver` around each one. In the
following lines, we create our own EventReceiver and register it with the
socket, thereby exposing all received events to an :class:`EventReceiver` that we can
access. Then, the most important part: we add the transceiver to the PoolManager.
After this point, the PoolManager will catch all RTC negotiation events received
and process them with each call to :meth:`PoolManager.update`.

After accepting and configuring new connections, we tell ``pools`` to update.
This is the bare minimum for RTC negotiations! The for-loop that follows is an
extra convenience for testing, not necessary for RTC negotiations. Essentially,
it catches all "describe" events and sets the description of the endpoint that
sent it to whatever JSON data was sent as the event data. After this, we do a
standard time.sleep() to give the CPU a break. And that's it! That's the RTC
server code.

A Minimal Client
----------------

I'm not here to tell you how to build the next Skype, Discord, or Microsoft Teams.
What I can do is show you how to make a simple video chat app that sufficiently
demonstrates how to put the front-end (rtcpool) to use along with the back-end (PyRTC).

So, let's get started! Create a directory for our mini project::

	$ mkdir minirtc
	$ cd minirtc

We'll be using npm, so let's start with the usual::

	$ npm init

Answer all the prompts, and then we can really get moving.
While the Python test server is a complete RTC signalling
Websocket server, it doesn't serve HTTP or provide the rtcpool
package. So we'll spin up a basic express.js server to do what we
need. We'll also need to get browserify for including rtcpool in
the client-side scripts::

	$ npm i rtcpool express browserify

Easy. Let's get started. Open up an editor window and enter this:

.. code-block:: javascript

	const express = require('express');
	const app = express();

	const browserify = require('browserify');
	const path = require('path');

	const script = browserify("client.js");

	app.get('/client.js', (req, res) => {
		script.bundle().pipe(res);
	});

	app.get('/:pool', (req, res) => {
		res.sendFile(path.resolve("client.html"));
	});

	app.listen(7000, () => {
		console.log("Listening on port 7000");
	});

That's it! Save this as index.js. This will serve our webpage and script.
We will leave this be for now, before we start our server, we've got
other matters to settle. We will use a very basic HTML page. After all,
we only really need a blank page with two video slots! Here's client.html.

.. code-block:: html

	<!DOCTYPE html>
	<html>
	  <head>
	    <title>MiniRTC</title>
	    <script src="/client.js"></script>
	    <style type="text/css">
	      html, body {
	        width: 100%;
	        height: 100%;
	        margin: 0;
	      }

	      div#videos {
	        position: absolute;
	        width: 90%;
	        height: 90%;
	        top: 5%;
	        left: 5%;
	      }
	      

	      video {
	        width: 45%;
	      }
	    </style>
	  </head>
	  <body>
	    <div id="videos">
	      <video autoplay playsinline id="me"></video>
	      <video autoplay playsinline id="notme"></video>
	    </div>
	  </body>
	</html>

Now, for our client.js. Look how short it is!

.. code-block:: javascript

	const rtcpool = require('rtcpool');

	window.onload = () => {
		const signal_socket = new WebSocket("ws://localhost:7001/");
		const signalling = new rtcpool.signalling.websocket(signal_socket);
		const pool = new rtcpool.Pool({
			"iceServers": [{
				"urls": [
					"stun:stun.l.google.com:19302"
				]
			}]
		}, signalling);

		const pool_name = location.pathname.substring(1);
		pool.join(pool_name);
		navigator.mediaDevices.getUserMedia({
			audio: true,
			video: true
		}).then(stream => {
			const media = new rtcpool.media.RTCStream(stream);
			pool.add_media(media);

			const me = document.querySelector('#me');
			console.log(me);
			me.srcObject = stream;
		});

		let conn = null;
		let stream = null;
		const notme = document.querySelector('#notme');
		pool.events.addEventListener('track', (evt) => {
			if (evt.connection !== conn) {
				conn = evt.connection;
				if (stream) {
					for (const track of stream.getTracks()) {
						track.stop();
					}
				}
				stream = new MediaStream();
				notme.srcObject = stream;
			}
			stream.addTrack(evt.track);
		});
	};

Now we need to add the PyRTC backend to our project::

	$ pip install pyrtc

In one terminal window, start the PyRTC test server like so::

	$ python -m pyrtc.test

In another terminal window, start our express server, ensuring
that you are in the project directory when you run this::

	$ node .

Now open two browser windows to ``http://localhost:7000/test``
and see the magic! Of course, make sure you grant access to the
camera and microphone, otherwise it won't work. To really help
sharpen your skills, take a shot at allowing more users to join
the chat room, with a new video screen showing up for each new user.