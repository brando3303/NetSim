import matplotlib.pyplot as plt
import numpy as np

def main() -> None:
  print("hello world")
  x = np.linspace(0, 10, 100)
  y = np.sin(x)
  plt.plot(x, y)
  plt.show()


if __name__ == "__main__":
	main()
