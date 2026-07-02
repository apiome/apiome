'use client';

import { useState } from 'react';
import type { Metadata } from "next";
import { Mail, MessageSquare, Send } from "lucide-react";
import { Button } from "../components/ui/Button";

export default function ContactPage() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    company: '',
    message: '',
  });
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // TODO: Implement actual form submission
    console.log('Form submitted:', formData);
    setSubmitted(true);
    setTimeout(() => {
      setSubmitted(false);
      setFormData({ name: '', email: '', company: '', message: '' });
    }, 3000);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setFormData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
  };

  return (
    <div className="flex flex-col">
      <section className="border-b border-zinc-200 bg-gradient-to-b from-white to-zinc-50 px-6 py-16 dark:border-zinc-800 dark:from-zinc-950 dark:to-zinc-900">
        <div className="container mx-auto max-w-4xl text-center">
          <h1 className="mb-4 text-5xl font-bold text-zinc-900 dark:text-zinc-50">
            Get in Touch
          </h1>
          <p className="text-xl text-zinc-600 dark:text-zinc-400">
            Have questions? We'd love to hear from you.
          </p>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="container mx-auto max-w-5xl">
          <div className="grid gap-12 lg:grid-cols-2">
            {/* Contact Info */}
            <div>
              <h2 className="mb-6 text-3xl font-bold text-zinc-900 dark:text-zinc-50">
                Let's talk about your project
              </h2>
              <p className="mb-8 text-lg text-zinc-600 dark:text-zinc-400">
                Whether you have questions about features, pricing, or need a demo, our team is ready to answer all your questions.
              </p>

              <div className="space-y-6">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-950 dark:text-blue-400">
                    <Mail className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="mb-1 font-semibold text-zinc-900 dark:text-zinc-50">
                      Email us
                    </h3>
                    <p className="text-zinc-600 dark:text-zinc-400">
                      support@apiome.app
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-950 dark:text-purple-400">
                    <MessageSquare className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="mb-1 font-semibold text-zinc-900 dark:text-zinc-50">
                      Join our community
                    </h3>
                    <p className="text-zinc-600 dark:text-zinc-400">
                      Connect with other developers and get help
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-12 rounded-2xl border border-zinc-200 bg-gradient-to-br from-blue-50 to-indigo-50 p-8 dark:border-zinc-800 dark:from-blue-950/20 dark:to-indigo-950/20">
                <h3 className="mb-2 text-xl font-bold text-zinc-900 dark:text-zinc-50">
                  Enterprise Support
                </h3>
                <p className="mb-4 text-zinc-600 dark:text-zinc-400">
                  Need dedicated support for your organization? Contact our sales team for custom solutions.
                </p>
                <a
                  href="mailto:sales@apiome.app"
                  className="text-blue-600 hover:underline dark:text-blue-400"
                >
                  sales@apiome.app
                </a>
              </div>
            </div>

            {/* Contact Form */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
              {submitted ? (
                <div className="flex h-full items-center justify-center text-center">
                  <div>
                    <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-green-600 dark:bg-green-950 dark:text-green-400">
                      <Send className="h-8 w-8" />
                    </div>
                    <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                      Message Sent!
                    </h3>
                    <p className="text-zinc-600 dark:text-zinc-400">
                      We'll get back to you as soon as possible.
                    </p>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  <div>
                    <label
                      htmlFor="name"
                      className="mb-2 block text-sm font-medium text-zinc-900 dark:text-zinc-50"
                    >
                      Name *
                    </label>
                    <input
                      type="text"
                      id="name"
                      name="name"
                      required
                      value={formData.name}
                      onChange={handleChange}
                      className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="email"
                      className="mb-2 block text-sm font-medium text-zinc-900 dark:text-zinc-50"
                    >
                      Email *
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      required
                      value={formData.email}
                      onChange={handleChange}
                      className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="company"
                      className="mb-2 block text-sm font-medium text-zinc-900 dark:text-zinc-50"
                    >
                      Company
                    </label>
                    <input
                      type="text"
                      id="company"
                      name="company"
                      value={formData.company}
                      onChange={handleChange}
                      className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="message"
                      className="mb-2 block text-sm font-medium text-zinc-900 dark:text-zinc-50"
                    >
                      Message *
                    </label>
                    <textarea
                      id="message"
                      name="message"
                      required
                      rows={6}
                      value={formData.message}
                      onChange={handleChange}
                      className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    />
                  </div>

                  <Button type="submit" className="w-full">
                    Send Message
                    <Send className="ml-2 h-4 w-4" />
                  </Button>
                </form>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
