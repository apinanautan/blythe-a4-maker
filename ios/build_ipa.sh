#!/bin/bash
# Build an unsigned BlytheEyeMaker.ipa (for sideloading) on a macOS machine with Xcode.
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' ../app/blythe_a4_maker.pyw)
export MARKETING_VERSION="$VERSION"
export BUILD_NUMBER="${GITHUB_RUN_NUMBER:-1}"
rm -rf web build out BlytheEyeMaker.ipa
cp -R ../mobile/web web
sed -i '' "s/__APP_VERSION__/$VERSION/" web/app.js
command -v xcodegen >/dev/null || brew install xcodegen
xcodegen generate
xcodebuild -project BlytheEyeMaker.xcodeproj -scheme BlytheEyeMaker -configuration Release -sdk iphoneos \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" build
mkdir -p out/Payload
cp -R build/Build/Products/Release-iphoneos/BlytheEyeMaker.app out/Payload/
(cd out && zip -qry ../BlytheEyeMaker.ipa Payload)
ls -la BlytheEyeMaker.ipa
