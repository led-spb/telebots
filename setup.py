#!/usr/bin/python
import setuptools
import telebots as module

setuptools.setup(
    name=module.name,
    version=module.version,
    author="Alexey Ponimash",
    author_email="alexey.ponimash@gmail.com",
    packages=setuptools.find_packages(exclude=["tests"]),
    install_requires=[
        'pytelegram_async>=0.1.0',
        'paho_async>=0.1.0',
        'tornado',
        'gpxpy',
        'bencode',
        'jinja2',
        'humanize',
        'lxml',
        'cssselect',
        'cachetools'
    ],
    dependency_links=[
        'https://github.com/led-spb/pytelegram_async/tarball/master#egg=pytelegram_async-0.1.0',
        'https://github.com/led-spb/paho_async/tarball/master#egg=paho_async-0.1.0',
    ],
    scripts=[
        'bin/torrentbot-notify.sh',
        'bin/notify'
    ],
    entry_points={
       'console_scripts': [
            'carbot = telebots.carbot:main',
            'homebot = telebots.homebot:main',
            'torrentbot = telebots.torrentbot:main'
       ]
    },
)
