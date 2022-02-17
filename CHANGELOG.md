# 2.0.0: February 17, 2022
- Updated to use ssp-v2
- Maintains compatibility with RTCPool 3.0.0, which still uses the `uid` field in some events

# 1.0.4: February 11, 2022
- ReadTheDocs build fix

# 1.0.3: February 11, 2022
- Fixed minor inconsistency where TransceiverManager.close_all() would not return an awaitable
  when in async mode
- Added documentation

# 1.0.2: February 8, 2022
- Added support for async/await
- Fixed description bug
	* Before, descriptions would not be sent to clients that join after a description is set
	* Now, descriptions are included in the rtc:joined event so that front-end APIs can assign
	  the appropriate description to peers when joined.

# 1.0.1: February 8, 2022
- Deleted version

# 1.0.0: Februrary 7, 2022
- Initial Release