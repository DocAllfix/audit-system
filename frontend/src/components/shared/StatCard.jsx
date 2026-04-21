import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Card, CardContent } from '@/components/ui/card';

export default function StatCard({ label, value, icon: Icon, trend, suffix = '' }) {
  const [displayValue, setDisplayValue] = useState(0);
  const numericValue = typeof value === 'number' ? value : parseInt(value) || 0;

  useEffect(() => {
    let start = 0;
    const duration = 600;
    const startTime = Date.now();
    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(Math.round(eased * numericValue));
      if (progress < 1) requestAnimationFrame(animate);
    };
    animate();
  }, [numericValue]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="glass card-glow relative overflow-hidden group hover:scale-[1.01] transition-transform duration-150">
        <CardContent className="p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
              <p className="text-3xl font-bold mt-2 text-foreground">
                {displayValue}{suffix}
              </p>
            </div>
            {Icon && (
              <div className="p-2.5 rounded-lg bg-primary/10">
                <Icon className="w-5 h-5 text-primary" />
              </div>
            )}
          </div>
          {trend && (
            <p className="text-xs mt-3 text-success font-medium">
              {trend}
            </p>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}