// Bounded stdin/stdout boundary. Music is data, never an executable module.
const parse = require('./abc-parser.cjs');
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', data => {
  input += data;
  if (input.length > 65536) process.exit(2);
});
process.stdin.on('end', () => {
  try {
    const request = JSON.parse(input);
    if (typeof request.abc !== 'string' || request.abc.length > 24000) throw Error('Invalid ABC input');
    const output = JSON.stringify(parse(request.abc));
    if (output.length > 2000000) throw Error('ABC parse result is too large');
    process.stdout.write(output);
  } catch (error) { process.stdout.write(JSON.stringify({error: String(error.message).slice(0, 500)})); process.exitCode = 1; }
});
