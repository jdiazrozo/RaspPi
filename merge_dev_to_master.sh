#!/bin/bash

# Exit if any command fails
set -e

echo "Switching to master branch..."
git checkout master

echo "Pulling latest changes from remote master..."
git pull origin master

echo "Merging dev into master..."
git merge dev

echo "Pushing merged master to remote..."
git push origin master

echo "✅ Merge complete! master is now updated with dev branch."