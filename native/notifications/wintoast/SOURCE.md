WinToast 1.3.2, MIT. Source: https://github.com/mohabouje/WinToast/tree/693efb90376809d1e1b4e6ce867171ce20fe7e76

Local changes: retain activation handlers after banner timeout so Notification Center items remain clickable; serialize notification-buffer access with a recursive mutex.

The host requests 24-hour notification validity using setExpiration; banners retain the system default duration.
