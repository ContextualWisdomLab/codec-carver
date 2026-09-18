#!/bin/bash
coverage run -m unittest discover tests
coverage run -a --source=saas_web -m unittest tests.test_saas_web
coverage report -m
