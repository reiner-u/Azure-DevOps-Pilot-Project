"""The converter window (tkinter). scripts/converter_gui.py starts it.

Pieces, from the bottom up:
    paths           where the exe / scripts / default folders are, and opening a file or folder
    settings_store  the window's remembered choices (gui_settings.json)
    summaries       the texts shown in the Details box and the status line (no tkinter, so they can be tested)
    runner          runs a conversion on a background thread and reports back through a queue
    widgets         shared tkinter helpers
    folder_bar      the folder and Area Path rows at the top
    file_list       the tick list of documents to convert
    results         the results table and the Details box
    defects_tab     the ALM Defect Converter tab (a "Work in Progress" placeholder for now)
    app             the main window: a Test Case Converter tab built from the panels above, plus the defects tab
    selftest        a hidden-window check used after building the exe
"""
