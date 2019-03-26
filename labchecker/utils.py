NOCOLOR = False


def _color(s, color='b'):
    global NOCOLOR
    if NOCOLOR:
        return s

    if color == 'b':
        return "\033[1;30m" + s + "\033[0m"
    elif color == 'r':
        return "\033[1;31m" + s + "\033[0m"
    elif color == 'g':
        return "\033[1;32m" + s + "\033[0m"
