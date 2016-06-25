from setuptools import setup

setup(
    name='aiometrics',
    use_scm_version=True,
    py_modules=['aiometrics'],
    url='https://github.com/dmonroy/aiometrics',
    license='MIT License',
    author='Darwin Monroy',
    author_email='contact@darwinmonroy.com',
    description='Generate metrics from AsyncIO applications',
    setup_requires=[
        'setuptools_scm'
    ],
    install_requires=[
        'aiohttp',
        'crontab'
    ]
)
