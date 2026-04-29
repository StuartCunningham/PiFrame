  ---                                                                                                                                                                              
  PiFrame Audit Report                                                                                                                                                             
                                                                                                                                                                                   
  Architecture: Sound, One Structural Problem                                                                                                                                      
                                                                                                                                                                                   
  The core design is correct: pygame and e-ink both require a single-threaded render loop, Flask in a daemon thread is fine, and the atomic state-via-properties pattern is clean. 
  The one structural problem is Flask's development server (app.run()). It's single-threaded, so a slow thumbnail generation request blocks every other request — including the    
  status poll the dashboard fires every 5 seconds. On a library page with 200 photos, the initial thumbnail burst will cause the dashboard to appear frozen. Drop in waitress      
  (already a common dep on Pi) and this disappears.                                                                                                                                
                                                                                                                                                                                   
  ---                                                                                                                                                                            
  Bugs                                                                                                                                                                             
                                                                                                                                                                                   
  1. Command queue is a single slot (real data loss)
  State._command holds one string. If the web UI sends next then reload in quick succession, one is silently dropped. It should be queue.Queue(maxsize=4) — send_command puts,     
  pop_command does get_nowait() with a default.
                                                                                                                                                                                
  2. OneDrive downloads corrupt files on failure                                                                                                                                
  _sync_folder writes directly to local_path. If the connection drops mid-download, the partial file sits at the destination. On the next sync, the size check
  (local_path.stat().st_size == remote_size) will fail so it re-downloads — unless the partial file happens to match the remote size, which would leave a corrupt image         
  permanently. Fix: download to local_path.with_suffix('.tmp') and os.replace() on success.
                                                                                                                                                                                   
  3. delete_local_removed is a no-op setting                                                                                                                                       
  config.yaml exposes it, the settings page has it, but _sync_folder never reads it. A user enabling it gets no deletions. Either implement it or remove the setting.              
                                                                                                                                                                                   
  4. Shared meta file for files with same stem
  photo.jpg and photo.png in the same directory both map to photo.json. If a user has both (legitimately or from a sync), they share metadata. The fix is {filename}.json not      
  {stem}.json.                         
                                                                                                                                                                                   
  5. draw_text_with_bg breaks on position='center-*'                                                                                                                            
  vert, horiz = position.split('-') — the middle case for vert == 'center' falls through to the else branch and uses h - block_h - pad (bottom). No overlay currently sends
  center-* but the position enum isn't enforced anywhere.                                                                                                                          
                                            
  6. Weather _maybe_refresh has a race window                                                                                                                                      
  _last_fetch is set before the thread fires, not after it completes — so two draw() calls within the same millisecond can both spawn a fetch thread. The instance _lock exists but
   isn't used in _maybe_refresh. Add with self._lock: around the check-and-update.                                                                                              
                                                                                                                                                                                   
  ---                                                                                                                                                                           
  Performance                                                                                                                                                                      
                                       
  1. Full image re-open and re-composite every display cycle — _show_current opens the raw image from disk, resizes it, and composites all overlays on every call. For a 60-second 
  slideshow with a 20MB DSLR JPEG this is fine, but with fade transitions (_fade at 30fps), that same image is never re-opened — _pil_to_surface is only called once per show. So
  the bottleneck is actually the resize+composite before the first frame, not repeated re-renders. Still, overlays that don't change (clock updates once a minute, weather every 30
   minutes) are being re-composited for every photo. Cache the composited surface keyed by (path, mtime, clock_minute).                                                         
                                                                                                                                                                                   
  2. Photo directory rescans every 5 minutes with full glob — _collect_photos does root.glob('**/*') on every reload. On a SD card with 5,000 files across subdirectories, this is
  slow and causes a visible pause. On Linux, inotify via the watchdog package would let you trigger reloads only on actual changes. Short term: increase the interval or make it
  lazy (scan only on reload command).                                                                                                                                           
                                                                                                                                                                                   
  3. Library API returns all files in one shot — api_library builds one JSON list of every file in the photo dir. If you have 2,000 photos, this is a large response, slow to
  render in the browser, and the thumbnail grid fires 2,000 lazy-load requests simultaneously. Pagination or virtual scrolling would fix this.                                     
                                                                                                                                                                                
  4. Thumbnail cache grows forever — .thumbcache/ is never pruned. A 400×300 JPEG thumbnail is ~30KB. After 5,000 photos that's 150MB on the SD card. Add a simple LRU eviction: on
   startup, sort by mtime and delete oldest if total size exceeds a threshold.
                                                                                                                                                                                   
  5. draw_text_with_bg allocates ~50MB per call on 1080p — It does image.copy().convert('RGBA') (~8MB), Image.new('RGBA', base.size) (~8MB), alpha_composite (~8MB), then back to
  RGB. Three large copies per overlay invocation. On a Pi this is measurable. Switch to direct ImageDraw on the image with a pre-rendered semi-transparent rectangle using         
  Image.alpha_composite on a smaller crop region rather than the full frame.                                                                                                    
                                                                                                                                                                                   
  Image.alpha_composite on a smaller crop region rather than the full frame.                                                                                                       
                                            
  ---                                                                                                                                                                              
  Security                                                                                                                                                                         
                                                                                                                
  1. secret_key = 'change-me-please' is shipped as a default — Flask session cookies are signed with this key. Anyone who reads this default (it's in the repo) can forge a session
   cookie. Fix: if the value matches the default at startup, generate and persist a random UUID to secrets.yaml.                                                                
                                         
  2. Password compared in plaintext — request.form.get('password') == config.web.get('password', ''). Use werkzeug.security.check_password_hash / generate_password_hash.         
                                            
  3. .piframe_token.json has default OS permissions — Contains OAuth bearer tokens. Should be written with os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600) in _save_cache.
                                                                                                                                                                                   
  4. No CSRF protection on any POST endpoint — /api/control, /api/media/meta, /settings all accept POST without a CSRF token. On a local network this is low risk, but a malicious
  page visited on the same network could trigger actions. Flask-WTF CSRF is one line of config.                                                                                    
                                       
  ---                                                                                                                                                                              
  Code Quality                                                                                                                                                              
                                                                                                                                                                                   
  Font system is too narrow — Only 10 hardcoded paths under /usr/share/fonts/truetype/. Custom fonts dropped in a project fonts/ directory won't be found. fc-list --format 
  '%{file}\n' | grep -i truetype would discover everything on the system dynamically.                                                                                              
                                                          
  Weather emoji won't render — DejaVu Sans doesn't have glyphs for 🌧 🌦 ⛈ ❄ 🌫. They'll be squares. The icon map should use only safe ASCII/Unicode values (like \u26c5 ⛅ which is
  in most Pi fonts) or skip icons when show_icon is False.                                                                                                                     
                                                                                                                                                              
  config.display returns a live dict reference — The convenience properties on Config return self._data['display'] directly. Any caller that mutates the returned dict bypasses    
  save(). Nothing currently does this, but it's an encapsulation leak that will bite eventually. Return copy.deepcopy or use __getattr__ to make it read-only.    
                                                                                                                                                                                   
  _load_image else branch swallows unknown fit modes silently — A typo in a JSON meta file (e.g. "fit_mode": "fil") falls through to center with no warning. Add a              
  _log.warning('Unknown fit_mode %r, falling back to center', fit_mode).                                                                                                           
                                                                                                                                                                                   
  api_sysinfo IP is unreliable — socket.gethostbyname(socket.getfqdn()) returns 127.0.1.1 on most Pi setups. Use socket.getaddrinfo(socket.gethostname(), None) and filter for  
  non-loopback, or read /proc/net/if_inet6 / iterate netifaces.                                                                                                                    
                                                                                                                                                                                   
  ---                                       
  Opinions                                                                                                                                                                         
                                                                                                                                                                                   
  The project is well-structured for its size. The separation between Config, State, display drivers, slideshow engine, and web layer is clean and the threading model is correct.
  The main things I'd actually change are:                                                                                                                                         
                                                                   
  1. Waitress instead of dev server — one-line change, immediate real-world improvement.          
  2. Fix the command queue — data loss bugs should always be fixed.                                                                                                                
  3. Fix OneDrive downloads — the temp-file rename is a two-line fix with real reliability impact.                                                                              
  4. Auto-generate secret_key — this is a shipped security default that affects all users who don't read the config carefully.                                                     
  5. Thumbnail cache pruning — SD cards are small; this will eventually fill one.                                                                                             
                                                                                                                                                                                
  Everything else is polish or nice-to-have. The e-ink flow, overlay compositing, and metadata system are all doing the right thing. The library UI is unusually capable for a  
  personal project.        
