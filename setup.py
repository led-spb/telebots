#!/usr/bin/python
import setuptools

setuptools.setup(
    name="telebots",
    version="0.1.0",
    author="Alexey Ponimash",
    author_email="alexey.ponimash@gmail.com",
    description="My useful telegram bots",
    long_description="",
    long_description_content_type="text/markdown",
    url="https://github.com/led-spb/telebots",
    packages=setuptools.find_packages(),
    install_requires=[
       'paho_mqtt',
       'asyncmqtt',
       'asynctelebot',
       'bencode',
       'tornado',
       'jinja2',
       'gpxpy',
       'humanize'
    ],
    scripts=[
        'bin/torrentbot-notify.sh'
    ],
    entry_points={
       'console_scripts': [
            'carbot = telebots.carbot:main',
            'homebot = telebots.homebot:main',
            'torrentbot = telebots.torrentbot:main'
       ]
    },
)
