from readchar import readkey, key
from styles import PALLET, STLYEL


def print_options():
    print("configure")
    print("run eval")
    print("display results")
    


def display_menu():

    while True: 
        print_options()
        k = readkey()
        match k: 
            case "q": 
                break
            case _: 
                continue 

if __name__ == "__main__":
    display_menu()
