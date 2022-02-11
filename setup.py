import pathlib
from setuptools import setup, find_packages

__dirname__ = pathlib.Path(__file__).parent
readme_text = (__dirname__ / "README.md").read_text()

setup(
	name="pyrtc",
	version="1.0.2",
	description="Python WebRTC signalling and connection management back-end.",
	long_description=readme_text,
	long_description_content_type="text/markdown",
	# TODO: url=
	author="Isaac Dorenkamp",
	author_email="unorthodox.isaac@gmail.com",
	license="MIT",
	classifiers=[
		"License :: OSI Approved :: MIT License",
		"Programming Language :: Python :: 3",
		"Programming Language :: Python :: 3.9"
	],
	package_dir={ "": "src" },
	packages=find_packages(where="src"),
	include_package_data=True,
	install_requires=["h11==0.13.0", "wsproto==1.0.0"]
)
