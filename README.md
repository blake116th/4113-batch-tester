# Blake's 4133 Batch Tester

This is a simple python script that automates batch testing for Columbia University's COMS4113 Distributed Systems.

Unlike the existing testing script, it runs tests concurrently when possible. As a result, it's much faster. (On the order of 25x to 50x for a normal testing load)

## Usage

You'll only need python3 to run this script. There are no additional dependencies.

To use this script, put batch-test.py in your project root. In a terminal, with your working directory as your project root, run

``` sh
python3 batch-test.py <homework-name>
```

The homework name should match the directory name in `src/`. Ex: `kvpaxos` or `mapreduce`.

## Configuration

There are a number of configuration options for this script -- just edit the constants at the top of the script.
