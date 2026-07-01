import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';

declare var introJs: any;

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent implements OnInit {
  title = 'Detailing Aid Converter';
  
  fileToUpload: File | null = null;
  isUploading = false;
  uploadError = '';
  
  projectId: string | null = null;
  pages: any[] = [];
  
  isGenerating = false;
  downloadUrl: string | null = null;
  activeModalPage: any = null;

  // Global nav positioning settings
  navArrowsPosition: string = 'none';  // 'top' | 'middle' | 'bottom' | 'none'
  homePosition: string = 'none';       // 'top-left' | 'top-right' | 'none'
  outputFormat: string = 'v9';         // 'v9' | 'sfe+'
  
  recentProjects: any[] = [];
  
  // New drawing state
  drawingMode: 'video' | 'home' | 'nav' | 'menu' = 'video';
  activeHotspot: any = null;
  
  API_BASE = (window as any).__ENV_API_BASE__ || 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.loadRecentProjects();
    // Show tour if first time
    if (!localStorage.getItem('tour_seen')) {
      setTimeout(() => this.startTour(), 1000);
      localStorage.setItem('tour_seen', 'true');
    }
  }

  loadRecentProjects() {
    this.http.get<any[]>(`${this.API_BASE}/projects`).subscribe({
      next: (data) => this.recentProjects = data,
      error: (err) => console.error('Failed to load recent projects', err)
    });
  }

  selectProject(projectSummary: any) {
    this.http.get<any>(`${this.API_BASE}/project/${projectSummary.id}`).subscribe({
      next: (project) => {
        this.projectId = project.id;
        // Defensive: ensure hotspots exist for all pages
        if (project.pages) {
          project.pages.forEach((p: any) => {
            if (!p.hotspots) p.hotspots = [];
          });
        }
        this.pages = project.pages.map((p: any, index: number) => ({
          ...p,
          new_html_name: index === 0 ? 'index.html' : (p.new_html_name || p.html_name),
          selected: (p.selected !== undefined) ? p.selected : true
        }));
        if (this.pages.length > 0) this.pages[0].selected = true; // Ensure index is locked
        
        this.navArrowsPosition = project.nav_arrows_position || 'none';
        this.homePosition = project.home_position || 'none';
        this.outputFormat = project.output_format || 'v9';
        this.downloadUrl = null;
        // Scroll to management view and auto-trigger workbench tour
        setTimeout(() => {
          document.querySelector('#step2-rename')?.scrollIntoView({ behavior: 'smooth' });
          this.tourPages();
        }, 500);
      },
      error: (err) => alert('Failed to load project details.')
    });
  }

  deleteProject(projectId: string, event: Event) {
    event.stopPropagation();
    if (confirm('Are you sure you want to delete this project?')) {
      this.http.delete(`${this.API_BASE}/project/${projectId}`).subscribe(() => {
        this.loadRecentProjects();
        if (this.projectId === projectId) {
          this.projectId = null;
          this.pages = [];
        }
      });
    }
  }

  startTour() {
    return; // Disabled to prevent click-blocking overlay bugs
  }
  
  tourPages() {
    return;
  }

  onFileChange(event: any) {
    if (event.target.files.length > 0) {
      this.fileToUpload = event.target.files[0];
    }
  }

  uploadFile() {
    if (!this.fileToUpload) return;
    
    this.isUploading = true;
    this.uploadError = '';
    
    const formData = new FormData();
    formData.append('file', this.fileToUpload);
    
    this.http.post<any>(`${this.API_BASE}/upload`, formData).subscribe({
      next: (res) => {
        this.projectId = res.project_id;
        // set default new names
        this.pages = res.pages.map((p: any, index: number) => ({
          ...p,
          new_html_name: index === 0 ? 'index.html' : p.html_name,
          hotspots: p.hotspots || [],
          selected: true // Default all selected
        }));
        this.isUploading = false;
        
        // Auto-trigger workbench tour for the new upload
        setTimeout(() => {
          this.tourPages();
        }, 800);
      },
      error: (err) => {
        this.uploadError = 'Upload failed. ' + (err.error?.detail || err.message);
        this.isUploading = false;
      }
    });
  }

  generateZip() {
    if (!this.projectId) return;
    
    this.isGenerating = true;

    const selectedPages = this.pages.filter(p => p.selected);
    const payload = {
      pages: selectedPages,
      nav_arrows_position: this.navArrowsPosition,
      home_position: this.homePosition,
      output_format: this.outputFormat
    };
    
    this.http.post<any>(`${this.API_BASE}/generate/${this.projectId}`, payload).subscribe({
      next: (res) => {
        // Ensure download URL is absolute
        this.downloadUrl = res.download_url.startsWith('http') ? res.download_url : `${this.API_BASE}${res.download_url}`;
        this.isGenerating = false;
      },
      error: (err) => {
        console.error('Generation Error:', err);
        const msg = err.error?.detail || 'Generation failed. Check server logs.';
        alert(msg);
        this.isGenerating = false;
      }
    });
  }

  downloadFinal() {
    if (this.downloadUrl) {
      window.open(this.downloadUrl, '_blank');
    }
  }

  resetApp() {
    this.projectId = null;
    this.fileToUpload = null;
    this.pages = [];
    this.downloadUrl = null;
    this.isGenerating = false;
    this.uploadError = '';
    this.activeModalPage = null;
    
    // reset file input visually if needed
    const fileInput: any = document.getElementById('fileInput');
    if (fileInput) fileInput.value = '';
  }
  
  previewAid() {
    if (this.pages.length > 0 && this.projectId) {
       const url = `${this.API_BASE}/storage/${this.projectId}/build/index.html`;
       window.open(url, '_blank');
    }
  }

  uploadSlideMedia(event: any, page: any) {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.type.startsWith('video/')) {
      alert("Please upload a valid matching video format.");
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    
    page.isUploadingMedia = true;

    this.http.post<any>(`${this.API_BASE}/project/${this.projectId}/media/${page.id}`, formData).subscribe({
      next: (res) => {
        page.video_name = res.video_name;
        page.isUploadingMedia = false;
        
        // Initialize default positioning (perfectly centered 80%)
        if (!page.video_top) page.video_top = 10;
        if (!page.video_left) page.video_left = 10;
        if (!page.video_width) page.video_width = 80;
        if (!page.video_height) page.video_height = 80;
      },
      error: (err) => {
        alert('Failed to attach video: ' + err.message);
        page.isUploadingMedia = false;
      }
    });
  }

  onMouseDown(event: MouseEvent, page: any) {
    // Prevent default drag
    event.preventDefault();
    page.isDrawing = true;
    
    const container = event.currentTarget as HTMLElement;
    const rect = container.getBoundingClientRect();
    
    // Calculate percentages
    const startX = ((event.clientX - rect.left) / rect.width) * 100;
    const startY = ((event.clientY - rect.top) / rect.height) * 100;
    page._startX = startX;
    page._startY = startY;

    if (this.drawingMode === 'video') {
      page.video_left = Math.max(0, Math.min(100, page._startX));
      page.video_top = Math.max(0, Math.min(100, page._startY));
      page.video_width = 0;
      page.video_height = 0;
    } else {
      // Create a new hotspot
      const newHotspot = {
        id: Math.random().toString(36).substr(2, 9),
        type: this.drawingMode,
        left: startX,
        top: startY,
        width: 0,
        height: 0,
        target: '',
        menuItems: this.drawingMode === 'menu' ? [] : undefined
      };
      page.hotspots.push(newHotspot);
      this.activeHotspot = newHotspot;
    }
  }

  onMouseMove(event: MouseEvent, page: any) {
    if (!page.isDrawing) return;
    event.preventDefault();

    const container = event.currentTarget as HTMLElement;
    const rect = container.getBoundingClientRect();
    
    const currentX = ((event.clientX - rect.left) / rect.width) * 100;
    const currentY = ((event.clientY - rect.top) / rect.height) * 100;
    
    let left = Math.min(page._startX, currentX);
    let top = Math.min(page._startY, currentY);
    let width = Math.abs(currentX - page._startX);
    let height = Math.abs(currentY - page._startY);
    
    // Boundary lock constraints
    if (left < 0) { width += left; left = 0; }
    if (top < 0) { height += top; top = 0; }
    if (left + width > 100) width = 100 - left;
    if (top + height > 100) height = 100 - top;
    
    if (this.drawingMode === 'video') {
      page.video_left = parseFloat(left.toFixed(1));
      page.video_top = parseFloat(top.toFixed(1));
      page.video_width = parseFloat(width.toFixed(1));
      page.video_height = parseFloat(height.toFixed(1));
    } else if (this.activeHotspot) {
      this.activeHotspot.left = parseFloat(left.toFixed(1));
      this.activeHotspot.top = parseFloat(top.toFixed(1));
      this.activeHotspot.width = parseFloat(width.toFixed(1));
      this.activeHotspot.height = parseFloat(height.toFixed(1));
    }
  }

  onMouseUp(page: any) {
    if (page.isDrawing) {
      page.isDrawing = false;
      this.activeHotspot = null;
    }
  }

  replicateHotspot(sourcePageId: string, hotspot: any, targetPageIds: string[] | 'all') {
    if (!hotspot) return;
    
    let targets: string[] = [];
    if (targetPageIds === 'all') {
      targets = this.pages.map(p => p.id).filter(id => id !== sourcePageId);
    } else {
      targets = targetPageIds.filter(id => id !== sourcePageId);
    }

    if (targets.length === 0) {
      alert("No slides selected. Please check at least one slide.");
      return;
    }

    this.pages.forEach(p => {
      if (targets.includes(p.id) && p.id !== this.activeModalPage?.id) {
        // ... (rest of logic same)
        // Avoid self-replication or duplicate replication based on type+pos
        const alreadyHas = p.hotspots.some((h: any) => 
          h.type === hotspot.type && h.top === hotspot.top && h.left === hotspot.left);
        
        if (!alreadyHas) {
          // Deep clone menu items if they exist
          const clonedItems = hotspot.menuItems ? JSON.parse(JSON.stringify(hotspot.menuItems)) : undefined;
          
          p.hotspots.push({
            ...hotspot,
            id: Math.random().toString(36).substr(2, 9),
            menuItems: clonedItems
          });
        }
      }
    });

    alert(`Hotspot replicated to ${targets.length === this.pages.length ? 'all' : targets.length} slides.`);
  }

  getSelectedPageIds(hi: number): string[] {
    const ids: string[] = [];
    this.pages.forEach((p, index) => {
      const el = document.getElementById(`check-${hi}-${p.id}`) as HTMLInputElement;
      if (el && el.checked) {
        ids.push(p.id);
      }
    });
    return ids;
  }

  clearVideo(page: any) {
    if (confirm("Clear video position and attached file?")) {
      page.video_name = null;
      page.video_top = null;
      page.video_left = null;
      page.video_width = null;
      page.video_height = null;
    }
  }

  deleteHotspot(page: any, hotspot: any) {
    page.hotspots = page.hotspots.filter((h: any) => h.id !== hotspot.id);
  }

  addMenuItem(hotspot: any) {
    if (!hotspot.menuItems) hotspot.menuItems = [];
    hotspot.menuItems.push({ label: 'New Item', target: '' });
  }

  removeMenuItem(hotspot: any, index: number) {
    hotspot.menuItems.splice(index, 1);
  }

  openModal(page: any) {
    this.activeModalPage = page;
    // Disable background scrolling to avoid messiness
    document.body.style.overflow = 'hidden';
  }

  closeModal() {
    this.activeModalPage = null;
    // Remount background scrolling
    document.body.style.overflow = '';
  }

  get selectedCount(): number {
    return this.pages.filter(p => p.selected).length;
  }

  toggleAll(selected: boolean) {
    this.pages.forEach((p, index) => {
      if (index === 0) return; // Keep index locked
      p.selected = selected;
    });
  }
}
