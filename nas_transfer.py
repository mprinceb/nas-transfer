#!/usr/bin/env python3
"""Desktop queue for up to fifteen mounted Trinet recording cards."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from nas_config import MOUNT_ROOT, NAS_PASSWORD
from nas_transfer_cli import (
    TransferCancelled, inventory, mount_nas, mounted_nas, removable_roots, transfer,
)

MAX_CARDS = 15


def size_label(size):
    return f'{size / 1024**3:.2f} GiB' if size >= 1024**3 else f'{size / 1024**2:.1f} MiB'


def valid_title(title):
    return bool(title) and title not in ('.', '..') and not any(c in title for c in '/\\\x00')


def scan_cards():
    cards, seen = [], set()
    for mount in removable_roots():
        source = mount / 'Trinet' / 'recording'
        if not source.is_dir():
            continue
        # Never follow a recording-folder alias to unrelated data.
        if source.resolve() != source:
            continue
        identity = (source.stat().st_dev, source.stat().st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        card = dict(source=source, mount=mount, title='', selected=False,
                    progress=0.0, destination='', phase='Ready', error='')
        try:
            files, _ = inventory(source)
            card.update(files=files, size=sum(s[2] for s in files.values()))
            card['phase'] = 'Ready' if files else 'Empty'
        except Exception as error:
            card.update(files={}, size=0, phase='Unreadable', error=str(error))
        cards.append(card)
    return cards


def run_batch(jobs, title, keep_source, cancel, notify):
    """Process one card at a time. Stop the queue on a failure or cancellation."""
    completed = 0
    for index, (key, card) in enumerate(jobs):
        if cancel.is_set():
            for pending, _ in jobs[index:]:
                notify(pending, dict(phase='Not started'))
            return completed, 'Stopped'
        try:
            destination = MOUNT_ROOT / datetime.datetime.now().strftime('%d%m%Y') / (card['title'] or title)
            transfer(card['source'], destination, keep_source,
                     notify=lambda event, key=key: notify(key, event),
                     cancel=cancel, expected=card['files'])
            completed += 1
        except Exception as error:
            phase = 'Stopped' if isinstance(error, TransferCancelled) else 'Failed'
            notify(key, dict(phase=phase, error=str(error), message=str(error)))
            for pending, _ in jobs[index + 1:]:
                notify(pending, dict(phase='Not started'))
            return completed, phase
    return completed, 'Complete'


class TransferApp:
    def __init__(self, root):
        self.root = root
        root.title('Ego · Trinet transfer')
        root.geometry('1180x800')
        root.minsize(960, 700)
        root.configure(bg='#eef2f7')
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.scanning = False
        self.connecting = False
        self.connected = False
        self.connection_id = 0
        self.connection_cancel = threading.Event()
        self.connection_timer = None
        self.closing = False
        self.cards = {}
        self.jobs = []
        self.host = tk.StringVar(value='smb://sxd')
        self.title_var = tk.StringVar()
        self.keep_source = tk.BooleanVar(value=False)
        self.connection = tk.StringVar(value='Connecting…')
        self.summary = tk.StringVar(value='Looking for mounted SD cards…')
        self.status = tk.StringVar(value='Ready when you are')
        self.progress = tk.DoubleVar()
        self.active = tk.StringVar(value='No transfer running')
        self._style()
        self._layout()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.pump)
        self.refresh_drives()
        root.after(200, self.connect)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('DejaVu Sans', 10))
        style.configure('TFrame', background='#eef2f7')
        style.configure('Panel.TFrame', background='white')
        style.configure('TLabel', background='#eef2f7', foreground='#17243a')
        style.configure('Panel.TLabel', background='white')
        style.configure('Muted.TLabel', foreground='#63738a')
        style.configure('TButton', padding=(12, 8))
        style.configure('Accent.TButton', background='#245cd6', foreground='white')
        style.map('Accent.TButton', background=[('active', '#1948b2'), ('disabled', '#99afd8')])
        style.configure('Treeview', rowheight=36, background='white', fieldbackground='white', foreground='#17243a', borderwidth=0)
        style.configure('Treeview.Heading', background='#e4eaf3', foreground='#40516b', padding=8, font=('DejaVu Sans', 9, 'bold'))
        style.map('Treeview', background=[('selected', '#dde9ff')], foreground=[('selected', '#17243a')])
        style.configure('Horizontal.TProgressbar', background='#245cd6', troughcolor='#dce5f1', borderwidth=0)
        style.configure('TCheckbutton', background='#eef2f7')

    def _layout(self):
        header = tk.Frame(self.root, bg='#17243a', padx=24, pady=18)
        header.pack(fill='x')
        tk.Label(header, text='EGO  /  TRINET TRANSFER', bg='#17243a', fg='#8fb5ff', font=('DejaVu Sans', 10, 'bold')).pack(anchor='w')
        tk.Label(header, text='From card to collection.', bg='#17243a', fg='white', font=('DejaVu Sans', 23, 'bold')).pack(anchor='w', pady=(5, 0))
        tk.Label(header, text='Up to 15 SD cards · One queue · Verified before cleanup', bg='#17243a', fg='#c4d0e1').pack(anchor='w', pady=(6, 0))
        body = ttk.Frame(self.root, padding=20)
        body.pack(fill='both', expand=True)
        connection = ttk.Frame(body, style='Panel.TFrame', padding=12)
        connection.pack(fill='x')
        ttk.Label(connection, text='NAS', style='Panel.TLabel', font=('DejaVu Sans', 10, 'bold')).pack(side='left', padx=(0, 12))
        self.host_entry = ttk.Entry(connection, textvariable=self.host, width=30)
        self.host_entry.pack(side='left', padx=(0, 8))
        self.connect_button = ttk.Button(connection, text='Connect', command=self.connect)
        self.connect_button.pack(side='left')
        self.cancel_connection_button = ttk.Button(connection, text='Cancel', command=self.cancel_connection, state='disabled')
        self.cancel_connection_button.pack(side='left', padx=6)
        ttk.Label(connection, textvariable=self.connection, style='Panel.TLabel').pack(side='right', padx=8)

        settings = ttk.Frame(body, padding=(0, 15))
        settings.pack(fill='x')
        ttk.Label(settings, text='Data title', font=('DejaVu Sans', 10, 'bold')).pack(side='left', padx=(0, 10))
        self.title_entry = ttk.Entry(settings, textvariable=self.title_var, width=30)
        self.title_entry.pack(side='left')
        ttk.Label(settings, text='Duplicates get -2, -3…', style='Muted.TLabel').pack(side='left', padx=12)
        self.keep_check = ttk.Checkbutton(settings, text='Keep source after verification', variable=self.keep_source)
        self.keep_check.pack(side='right')

        toolbar = ttk.Frame(body)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Label(toolbar, textvariable=self.summary, font=('DejaVu Sans', 10, 'bold')).pack(side='left')
        self.scan_button = ttk.Button(toolbar, text='Rescan cards', command=self.refresh_drives)
        self.scan_button.pack(side='right')
        self.select_button = ttk.Button(toolbar, text='Select up to 15', command=self.select_all)
        self.select_button.pack(side='right', padx=6)
        self.clear_button = ttk.Button(toolbar, text='Clear selection', command=self.clear_selection)
        self.clear_button.pack(side='right')

        table = ttk.Frame(body)
        table.pack(fill='both', expand=True)
        columns = ('selected', 'card', 'files', 'size', 'title', 'state', 'progress')
        self.table = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse', height=4)
        for name, text, width in zip(columns, ('Use', 'SD card / mount', 'Files', 'Size', 'Title override', 'Status', 'Progress'), (50, 280, 60, 90, 170, 185, 90)):
            self.table.heading(name, text=text)
            self.table.column(name, width=width, minwidth=45, stretch=name in ('card', 'title', 'state'))
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.table.tag_configure('complete', foreground='#177346')
        self.table.tag_configure('failed', foreground='#b62d36')
        self.table.bind('<Button-1>', self.toggle_card)
        self.table.bind('<Double-1>', self.edit_title)
        ttk.Label(body, text='Click “Use” to select a card. Double-click a row to set its own title. Stop recording before transferring.', style='Muted.TLabel').pack(anchor='w', pady=(7, 12))

        footer = ttk.Frame(body)
        footer.pack(fill='x')
        self.start_button = ttk.Button(footer, text='Transfer selected cards', style='Accent.TButton', command=self.start_transfer)
        self.start_button.pack(side='right')
        self.stop_button = ttk.Button(footer, text='Stop queue', command=self.stop, state='disabled')
        self.stop_button.pack(side='right', padx=8)
        ttk.Label(footer, textvariable=self.status, font=('DejaVu Sans', 10, 'bold')).pack(side='left')
        ttk.Progressbar(body, variable=self.progress, maximum=100).pack(fill='x', pady=(12, 6))
        ttk.Label(body, textvariable=self.active, style='Muted.TLabel', wraplength=1060).pack(anchor='w')
        self.log = tk.Text(body, height=4, bg='#e4eaf3', fg='#40516b', relief='flat', padx=10, pady=8, font=('DejaVu Sans Mono', 9), state='disabled', wrap='word')
        self.log.pack(fill='x', pady=(10, 0))

    def append(self, text):
        text = text.replace(NAS_PASSWORD, '[redacted]')
        self.log.configure(state='normal')
        self.log.insert('end', text.strip() + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def lock_controls(self):
        state = 'disabled' if self.busy or self.scanning else 'normal'
        for widget in (self.scan_button, self.select_button, self.clear_button, self.title_entry, self.keep_check):
            widget.configure(state=state)
        for widget in (self.connect_button, self.host_entry):
            widget.configure(state='disabled' if self.busy or self.connecting else 'normal')
        self.start_button.configure(state='disabled' if self.busy or self.scanning or self.connecting or not self.connected else 'normal')
        self.cancel_connection_button.configure(state='normal' if self.connecting else 'disabled')
        self.stop_button.configure(state='normal' if self.busy else 'disabled')

    def render_card(self, key):
        card = self.cards[key]
        tag = 'complete' if card['phase'].startswith('Complete') else 'failed' if card['phase'] in ('Failed', 'Unreadable') else ''
        values = ('●' if card['selected'] else '○', str(card['mount']), len(card['files']), size_label(card['size']), card['title'] or 'Use data title', card['phase'], f"{card['progress']:.0%}")
        self.table.item(key, values=values, tags=(tag,))

    def update_summary(self):
        selected = [c for c in self.cards.values() if c['selected']]
        self.summary.set(f'{len(self.cards)} cards found  ·  {len(selected)}/15 selected  ·  {size_label(sum(c["size"] for c in selected))}')

    def refresh_drives(self):
        if self.busy or self.scanning:
            return
        self.scanning = True
        self.lock_controls()
        self.summary.set('Scanning mounted removable drives…')
        def worker():
            try:
                self.events.put(('scan', scan_cards()))
            except Exception as error:
                self.events.put(('scan_error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def select_all(self):
        if self.busy:
            return
        count = 0
        for key, card in self.cards.items():
            card['selected'] = bool(card['files']) and card['phase'] == 'Ready' and count < MAX_CARDS
            count += int(card['selected'])
            self.render_card(key)
        self.update_summary()

    def clear_selection(self):
        if self.busy:
            return
        for key, card in self.cards.items():
            card['selected'] = False
            self.render_card(key)
        self.update_summary()

    def toggle_card(self, event):
        if self.busy or self.scanning or self.table.identify_column(event.x) != '#1':
            return
        key = self.table.identify_row(event.y)
        if not key:
            return
        card = self.cards[key]
        if card['phase'] != 'Ready':
            return
        if not card['selected'] and sum(c['selected'] for c in self.cards.values()) >= MAX_CARDS:
            messagebox.showinfo('Queue full', 'Select up to 15 cards for one batch.', parent=self.root)
            return
        card['selected'] = not card['selected']
        self.render_card(key)
        self.update_summary()

    def edit_title(self, event):
        if self.busy or self.scanning or self.table.identify_column(event.x) == '#1':
            return
        key = self.table.identify_row(event.y)
        if not key:
            return
        card = self.cards[key]
        title = simpledialog.askstring('Card data title', f'{card["mount"]}\nLeave blank to use the shared data title.', initialvalue=card['title'], parent=self.root)
        if title is None:
            return
        title = title.strip()
        if title and not valid_title(title):
            messagebox.showerror('Invalid title', 'Use a folder name without slashes.', parent=self.root)
            return
        card['title'] = title
        self.render_card(key)

    def connect(self):
        if self.busy or self.connecting:
            return
        address = self.host.get().strip()
        self.connecting = True
        self.connected = False
        self.connection.set('Connecting…')
        self.connection_id += 1
        attempt = self.connection_id
        cancel = self.connection_cancel = threading.Event()
        self.connection_timer = self.root.after(40000, lambda: self.connection_timed_out(attempt))
        self.lock_controls()
        def worker():
            try:
                mount_nas(address, authorization='pkexec', cancel=cancel)
                self.events.put(('connected', (attempt, address)))
            except Exception as error:
                self.events.put(('connection_error', (attempt, str(error))))
        threading.Thread(target=worker, daemon=True).start()

    def cancel_connection(self):
        self.connection_cancel.set()
        self.connection_id += 1  # Discard late results from a cancelled attempt.
        if self.connection_timer is not None:
            self.root.after_cancel(self.connection_timer)
            self.connection_timer = None
        self.connecting = False
        self.connected = False
        self.connection.set('Not connected')
        self.lock_controls()

    def connection_timed_out(self, attempt):
        if self.connecting and self.connection_id == attempt:
            self.cancel_connection()
            self.append('NAS connection timed out. Enter its IP address and click Connect.')
            self.prompt_nas_address()

    def prompt_nas_address(self, reason='NAS connection failed.'):
        if self.closing:
            return
        reason = reason.replace(NAS_PASSWORD, '[redacted]')
        address = simpledialog.askstring('Connect to NAS', f'{reason}\n\nEnter an address such as smb://sxd/Ego or 192.168.1.50.\nSaved credentials will be used.', initialvalue=self.host.get(), parent=self.root)
        if address and address.strip():
            self.host.set(address.strip())
            self.connect()

    def start_transfer(self):
        if self.busy or self.scanning or self.connecting:
            return
        jobs = [(key, dict(card)) for key, card in self.cards.items() if card['selected'] and card['phase'] == 'Ready']
        if not self.connected or not mounted_nas():
            messagebox.showerror('Connect the NAS', 'Connect to the NAS before starting the queue.', parent=self.root)
            return
        if not 1 <= len(jobs) <= MAX_CARDS:
            messagebox.showinfo('Select cards', 'Select between 1 and 15 ready cards.', parent=self.root)
            return
        title = self.title_var.get().strip()
        if any(not valid_title(card['title'] or title) for _, card in jobs):
            messagebox.showerror('Data title required', 'Give every selected card a valid shared or individual data title.', parent=self.root)
            return
        keep = self.keep_source.get()
        action = 'Source files will be kept.' if keep else 'Verified files will be cleared from each SD card.'
        if not messagebox.askyesno('Start transfer queue', f'Transfer {len(jobs)} cards to Ego/date/title?\nEach card gets a separate folder with automatic numbering.\n\n{action}', parent=self.root):
            return
        self.busy = True
        self.jobs = jobs
        self.cancel.clear()
        self.progress.set(0)
        for key, _ in jobs:
            self.cards[key].update(phase='Queued', progress=0.0)
            self.render_card(key)
        self.lock_controls()
        self.status.set(f'0 / {len(jobs)} cards complete')
        self.append(f'Started queue: {len(jobs)} cards. {action}')
        def worker():
            result = run_batch(jobs, title, keep, self.cancel,
                               lambda key, event: self.events.put(('card', (key, event))))
            self.events.put(('finished', result))
        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        self.cancel.set()
        self.stop_button.configure(state='disabled')
        self.status.set('Stopping after the current I/O operation…')

    def close(self):
        if self.busy:
            self.stop()
            self.append('Stopping the queue. Close the window once it has stopped. Verified files already cleared remain on the NAS.')
        else:
            self.closing = True
            self.cancel_connection()
            self.root.destroy()

    def pump(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'scan':
                previous = {c['source']: c['title'] for c in self.cards.values()}
                self.cards = {str(i): card for i, card in enumerate(value)}
                for key in self.table.get_children():
                    self.table.delete(key)
                for key, card in self.cards.items():
                    card['title'] = previous.get(card['source'], '')
                    self.table.insert('', 'end', iid=key)
                    self.render_card(key)
                    if card['error']:
                        self.append(f'{card["mount"]}: {card["error"]}')
                self.scanning = False
                self.select_all()
                self.lock_controls()
                if not value:
                    self.append('No mounted cards with Trinet/recording found. Mount the cards in your file manager, then rescan.')
            elif kind == 'scan_error':
                self.scanning = False
                self.summary.set('Card scan failed — try Rescan cards')
                self.append(value)
                self.lock_controls()
            elif kind in ('connected', 'connection_error'):
                attempt, value = value
                if attempt != self.connection_id or self.closing:
                    continue
                if self.connection_timer is not None:
                    self.root.after_cancel(self.connection_timer)
                    self.connection_timer = None
                self.connecting = False
                self.connected = kind == 'connected'
                self.connection.set('Connected · Ego' if self.connected else 'Not connected')
                self.lock_controls()
                if self.connected:
                    self.append(f'NAS connected: {value} → {MOUNT_ROOT}')
                else:
                    self.append(value)
                    self.prompt_nas_address(value)
            elif kind == 'card':
                key, event = value
                self.cards[key].update({k: v for k, v in event.items() if k != 'message'})
                self.render_card(key)
                if 'message' in event:
                    self.append(f'{self.cards[key]["mount"]}: {event["message"]}')
                count = sum(self.cards[k]['phase'].startswith('Complete') for k, _ in self.jobs)
                self.progress.set(100 * sum(self.cards[k]['progress'] for k, _ in self.jobs) / len(self.jobs))
                self.status.set(f'{count} / {len(self.jobs)} cards complete')
                card = self.cards[key]
                self.active.set(f'{card["mount"]} · {card["phase"]} · {card["destination"]}')
            elif kind == 'finished':
                self.busy = False
                count, phase = value
                self.status.set(f'{phase} · {count}/{len(self.jobs)} cards complete')
                self.append(f'Queue {phase.lower()}. {count}/{len(self.jobs)} cards complete.')
                if phase != 'Complete':
                    self.append('Remaining cards were not started. Partial NAS copies are retained. Some verified files may already have been cleared. Rescan before retrying.')
                self.lock_controls()
        if not self.closing:
            self.root.after(50, self.pump)


def main():
    root = tk.Tk()
    TransferApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
