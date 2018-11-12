#!/usr/bin/python

import setuptools
                  

setuptools.setup(
    name="telebots",
    version="0.0.1",
    author="Alexey Ponimash",
    author_email="alexey.ponimash@gmail.com",
    description="Some telegram bots",
    long_description="",
    long_description_content_type="text/markdown",
    url="https://github.com/pypa/sampleproject",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
       'requests>=2.10.0',
       'pysocks',
       'paho_mqtt',
#       'lxml>=2.0',
#       'cssselect',
#       'pyyaml>3.10',
    ],
    entry_points={
       'console_scripts': [
            'homebot = telebots.homebot:main',
            'torrentbot = telebots.torrentbot:main',
            'khlbot = telebots.khlbot:main',
       ]
    },
)
