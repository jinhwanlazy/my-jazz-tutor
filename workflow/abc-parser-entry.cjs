// Private adapter for the pinned abcjs parser. Do not expose its AST as our API.
// This avoids the deprecated parseOnly API and never needs a browser/DOM.
const Parse = require('abcjs/src/parse/abc_parse');
module.exports = function parse(source) {
  const parser = new Parse();
  parser.parse(source, {});
  const tune = parser.getTune();
  return {engine: 'abcjs-6.7.2', warnings: parser.getWarnings() || [],
    lines: tune.lines, meta: tune.metaText};
};
