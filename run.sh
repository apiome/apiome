#!/usr/bin/env bash
#
# Start script for the suite

cd apiome-db ; apiome-db migrate
cd ..
yarn install
yarn dev

