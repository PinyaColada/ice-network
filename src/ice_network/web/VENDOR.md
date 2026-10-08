The offline replay embeds a tree-shaken Three.js 0.180.0 + OrbitControls bundle.
License: THREE-LICENSE.txt (MIT). No CDN or npm is needed to use the replay.

To rebuild the vendor bundle, install three@0.180.0 and esbuild@0.25.10 in a temporary
directory, then copy vendor.entry.js into it. Bundle with:

    esbuild vendor.entry.js --bundle --minify --format=iife --global-name=ICE3D --outfile=three.min.js

The authored replay.js, scene.js, CSS and HTML remain unbundled for readability.
Three.js documentation: https://threejs.org/manual/#en/installation
