import os
from setuptools import find_packages, setup

with open(os.path.join(os.path.dirname(__file__), 'README.md')) as readme:
    README = readme.read()

os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='openimis-be-legacy_individual',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    license='GNU AGPL v3',
    description='openIMIS Backend module for archived PSSN legacy person and household data.',
    long_description=README,
    long_description_content_type='text/markdown',
    url='https://openimis.org/',
    author='TASAF',
    author_email='dev@tasaf.go.tz',
    install_requires=[
        'django',
        'djangorestframework',
        'openimis-be-core',
    ],
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Framework :: Django :: 3.0',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.10',
    ],
)
