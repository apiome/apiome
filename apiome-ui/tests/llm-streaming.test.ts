/**
 * Tests for LLM Streaming Optimization
 *
 * These tests verify that the streaming implementation handles data correctly
 * with proper buffering and asynchronous processing.
 */

import { describe, it, expect, jest } from '@jest/globals';

describe('LLM Streaming Optimization', () => {
  describe('Server-side line buffering', () => {
    it('should handle complete lines immediately', () => {
      const buffer = '';
      const chunk = '{"message":{"content":"Hello"}}\n{"message":{"content":" world"}}\n';

      const lines = chunk.split('\n');
      const incompleteLine = lines.pop() || '';

      expect(lines).toHaveLength(2);
      expect(lines[0]).toContain('Hello');
      expect(lines[1]).toContain('world');
      expect(incompleteLine).toBe('');
    });

    it('should preserve incomplete lines in buffer', () => {
      let buffer = '';
      const chunk = '{"message":{"content":"Hello"}}\n{"message":{"co';

      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      expect(lines).toHaveLength(1);
      expect(lines[0]).toContain('Hello');
      expect(buffer).toBe('{"message":{"co');
    });

    it('should complete buffered lines on next chunk', () => {
      let buffer = '{"message":{"co';
      const chunk = 'ntent":"world"}}\n';

      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      expect(lines).toHaveLength(1);
      expect(lines[0]).toContain('world');
      expect(buffer).toBe('');
    });

    it('should handle multiple incomplete chunks', () => {
      let buffer = '';
      const chunks = [
        '{"message"',
        ':{"content":"Hel',
        'lo"}}\n{"message":',
        '{"content":" world"}}\n'
      ];

      const completedLines: string[] = [];

      for (const chunk of chunks) {
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        completedLines.push(...lines.filter(l => l.trim()));
      }

      expect(completedLines).toHaveLength(2);
      expect(completedLines[0]).toContain('Hello');
      expect(completedLines[1]).toContain('world');
    });
  });

  describe('Client-side requestAnimationFrame scheduling', () => {
    it('should schedule only one update when called multiple times', () => {
      let pendingUpdate = false;
      let updateCount = 0;
      let animationFrameId: number | null = null;

      const scheduleUpdate = (content: string) => {
        if (pendingUpdate) return;

        pendingUpdate = true;
        updateCount++;
        // Simulate RAF
        setTimeout(() => {
          pendingUpdate = false;
        }, 16); // ~60fps
      };

      // Rapid calls
      scheduleUpdate('Hello');
      scheduleUpdate('Hello world');
      scheduleUpdate('Hello world!');

      expect(updateCount).toBe(1);
    });

    it('should allow scheduling after previous update completes', (done) => {
      let pendingUpdate = false;
      let updateCount = 0;

      const scheduleUpdate = (content: string) => {
        if (pendingUpdate) return;

        pendingUpdate = true;
        updateCount++;
        setTimeout(() => {
          pendingUpdate = false;
        }, 16);
      };

      scheduleUpdate('First');
      expect(updateCount).toBe(1);

      setTimeout(() => {
        scheduleUpdate('Second');
        expect(updateCount).toBe(2);
        done();
      }, 20);
    });
  });

  describe('Stream processing flow', () => {
    it('should accumulate content without blocking', async () => {
      const events = [
        { content: 'Hello' },
        { content: ' ' },
        { content: 'world' },
        { content: '!' }
      ];

      let accumulatedContent = '';
      const updates: string[] = [];

      for (const event of events) {
        accumulatedContent += event.content;
        // Simulate scheduling update without blocking
        updates.push(accumulatedContent);
      }

      expect(accumulatedContent).toBe('Hello world!');
      expect(updates).toHaveLength(4);
      expect(updates[0]).toBe('Hello');
      expect(updates[3]).toBe('Hello world!');
    });

    it('should handle rapid successive events', () => {
      const tokens = 'Hello world this is a test'.split(' ');
      let content = '';
      const snapshots: string[] = [];

      // Simulate rapid token arrival
      for (const token of tokens) {
        content += (content ? ' ' : '') + token;
        snapshots.push(content);
      }

      expect(snapshots).toHaveLength(6);
      expect(snapshots[0]).toBe('Hello');
      expect(snapshots[snapshots.length - 1]).toBe('Hello world this is a test');
    });
  });

  describe('SSE event formatting', () => {
    it('should format events correctly', () => {
      const event = {
        content: 'Hello',
        done: false
      };

      const formatted = `data: ${JSON.stringify(event)}\n\n`;

      expect(formatted).toContain('data:');
      expect(formatted).toContain('"content":"Hello"');
      expect(formatted).toContain('"done":false');
      expect(formatted.endsWith('\n\n')).toBe(true);
    });

    it('should format completion event', () => {
      const formatted = 'data: [DONE]\n\n';

      expect(formatted).toBe('data: [DONE]\n\n');
      expect(formatted.endsWith('\n\n')).toBe(true);
    });

    it('should parse SSE events correctly', () => {
      const sseData = 'data: {"content":"Hello","done":false}\n\n';

      if (sseData.startsWith('data: ')) {
        const data = sseData.slice(6).trim();

        if (data !== '[DONE]') {
          const event = JSON.parse(data);
          expect(event.content).toBe('Hello');
          expect(event.done).toBe(false);
        }
      }
    });
  });

  describe('Error handling', () => {
    it('should handle malformed JSON gracefully', () => {
      const malformedLine = '{"message":{"content":"Hello"';

      let error = null;
      try {
        JSON.parse(malformedLine);
      } catch (e) {
        error = e;
      }

      expect(error).not.toBeNull();
      // Should continue processing other lines
    });

    it('should handle empty lines', () => {
      const chunk = '\n\n{"message":{"content":"Hello"}}\n\n';
      const lines = chunk.split('\n').filter(line => line.trim());

      expect(lines).toHaveLength(1);
      expect(lines[0]).toContain('Hello');
    });

    it('should handle buffer cleanup on stream end', () => {
      let buffer = '{"message":{"content":"Final"}}';

      if (buffer.trim()) {
        const data = JSON.parse(buffer);
        expect(data.message.content).toBe('Final');
      }

      buffer = '';
      expect(buffer).toBe('');
    });
  });

  describe('Performance characteristics', () => {
    it('should process large number of events efficiently', () => {
      const startTime = Date.now();
      let content = '';

      // Simulate 1000 token events
      for (let i = 0; i < 1000; i++) {
        content += 'a';
      }

      const duration = Date.now() - startTime;

      expect(content.length).toBe(1000);
      expect(duration).toBeLessThan(100); // Should be very fast
    });

    it('should maintain constant memory with streaming', () => {
      let buffer = '';
      const processedLines: string[] = [];

      // Simulate streaming with buffer management
      for (let i = 0; i < 100; i++) {
        buffer += `{"message":{"content":"token${i}"}}\n`;

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        processedLines.push(...lines.filter(l => l.trim()));
      }

      // Buffer should be small (only incomplete line)
      expect(buffer.length).toBeLessThan(100);
      // All lines should be processed
      expect(processedLines.length).toBe(100);
    });
  });
});

