// src/lib/api.ts

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface Meeting {
  id: string;
  title: string;
  start_time: string;
  status: string;
  source: string;
  has_transcript: boolean;
}

export interface BotStatus {
  is_running: boolean;
  status: string;
  last_activity: string | null;
  active_meetings: string[];
}

export interface TranscriptChunk {
  speaker: string;
  content: string;
  index: number;
}

export interface MeetingDetail extends Meeting {
  end_time: string;
  transcript: string;
  chunks: TranscriptChunk[];
}

class APIService {
  private baseUrl: string;

  constructor() {
    this.baseUrl = API_BASE_URL;
  }

  private async fetchWithAuth(endpoint: string, options: RequestInit = {}) {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  // Bot endpoints
  async getBotStatus(): Promise<BotStatus> {
    return this.fetchWithAuth('/api/bot/status');
  }

  async startBot() {
    return this.fetchWithAuth('/api/bot/start', { method: 'POST' });
  }

  async stopBot() {
    return this.fetchWithAuth('/api/bot/stop', { method: 'POST' });
  }

  // Meetings endpoints
  async getMeetings(limit: number = 10): Promise<{ meetings: Meeting[], total: number }> {
    return this.fetchWithAuth(`/api/meetings?limit=${limit}`);
  }

  async getMeeting(id: string): Promise<MeetingDetail> {
    return this.fetchWithAuth(`/api/meetings/${id}`);
  }

  async processTranscript(transcriptPath: string) {
    return this.fetchWithAuth('/api/transcripts/process', {
      method: 'POST',
      body: JSON.stringify({ transcript_path: transcriptPath }),
    });
  }

  async healthCheck() {
    return this.fetchWithAuth('/api/health');
  }
}

export const api = new APIService();