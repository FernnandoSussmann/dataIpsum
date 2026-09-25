import subprocess
import sys


def run_command(user_input: str) -> None:
    subprocess.run(user_input, shell=True)


if __name__ == "__main__":
    run_command(sys.argv[1])
