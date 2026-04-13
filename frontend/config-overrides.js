const webpack = require('webpack');

module.exports = function override(config) {
  const fallback = config.resolve.fallback || {};
  Object.assign(fallback, {
    "url": require.resolve("url/"),
    "http": require.resolve("stream-http"),
    "https": require.resolve("https-browserify"),
    "stream": require.resolve("stream-browserify"),
    "assert": require.resolve("assert/"),
    "process/browser": require.resolve("process/browser"),
    "buffer": require.resolve("buffer/"),
  });
  config.resolve.fallback = fallback;
  config.plugins = (config.plugins || []).concat([
    new webpack.ProvidePlugin({
      process: 'process/browser',
      Buffer: ['buffer', 'Buffer'],
    }),
  ]);
  return config;
};

