#!/bin/bash
set -euo pipefail

coverage run --source=saas_web -m unittest discover tests
coverage report -m
